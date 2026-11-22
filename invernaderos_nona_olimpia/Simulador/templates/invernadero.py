"""
Simulador de invernadero
========================

Variables: temperatura interna/externa y radiación solar interna/externa (W/m²).

Estructura (cada bloque es independiente y se puede mover a su propio módulo/app de Django):

    ConfigInvernadero  parámetros físicos y de simulación
    TipoClima / AccionInterior / EstadoTecho / EstadoCortinas   enumeraciones
    EventoClimatico / EventoInterior                            eventos agendables (inicio y fin)
    Agenda             colección thread-safe de eventos
    RelojSimulado      tiempo simulado, velocidad ajustable en caliente y pausa
    CicloDiario        día de 24 h: noche, amanecer, atardecer, radiación solar
    ClimaExterior      temperatura y radiación exteriores (ciclo diario + eventos)
    Invernadero        interior: techo, cortinas, ventiladores y su respuesta retardada
    Historial          mediciones registradas (para graficar)
    Simulador          orquestador; corre en un hilo propio mientras se usa desde afuera
    Visualizador       gráficos en vivo + controles (matplotlib, opcional)

Modelo en una línea
-------------------
Exterior:  T_ext = T_base - descenso_nocturno * noche + Σ ΔT_evento * nivel_evento
           Rad_ext = Rad_solar(hora) * Π factor_evento(nivel)
Interior:  Rad_int = Rad_ext * transmisión_techo
           T_obj   = T_ext
           tau_ret = tau_retardo_base_s * mult_techo * mult_cortinas * mult_clima
           dT_lag/dt = (T_obj - T_lag) / tau_ret
           T_int = T_lag - enfriamiento_ventiladores * |T_lag| * nivel_ventiladores
           t90 = tau_ret * ln(10)   -> tiempo en que el interior cubre el 90 % de la diferencia con el exterior

Ventiladores: NO cambian el retardo; enfrían directamente el interior un 15 % (configurable),
  sin depender del clima, del techo ni de las cortinas. El efecto entra y sale de forma gradual.

Estado por defecto (sin eventos): techo CERRADO, cortinas CERRADAS, ventiladores APAGADOS.
  techo y cortinas cerrados ........ t90 ~ 2.3 h  (el interior sigue muy lento al exterior)
  cortinas abiertas ................ t90 ~ 48 min
  cortinas + techo abiertos ........ t90 ~ 15 min (el interior alcanza casi la temperatura exterior)

Requiere Python 3.10+. matplotlib solo hace falta para el Visualizador.

Notas para Django (buscar los comentarios "DJANGO:")
----------------------------------------------------
  * ConfigInvernadero  -> modelo (o settings) por invernadero.
  * Agenda/Evento*     -> modelos con ForeignKey al invernadero; las clases de acá solo reciben objetos.
  * Historial/Medicion -> modelo Medicion (bulk_create cada N registros).
  * Simulador          -> NO debe vivir en el proceso web (hay varios workers). Correrlo como
                          management command / proceso aparte / tarea Celery, y comunicarse por BD o Redis.
  * Visualizador       -> se reemplaza por el front (Chart.js/WebSocket con Channels). Para eso existe
                          Medicion.como_dict().
  * Fechas: acá son naive. Con USE_TZ=True usar django.utils.timezone (aware) de punta a punta.
"""


from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from functools import partial
from typing import NamedTuple


# =========================================================================== #
# 1. Enumeraciones
# =========================================================================== #
# DJANGO: pasar a models.TextChoices (mismos valores).
class TipoClima(str, Enum):
    SOL_INTENSO = "Sol intenso"
    NUBLADO = "Nublado"
    LLUVIA = "Lluvia"
    TORMENTA_ELECTRICA = "Tormenta eléctrica"
    TORMENTA = "Tormenta"
    FRIO_INTENSO = "Frío intenso"


class AccionInterior(str, Enum):
    APERTURA_TECHO = "Apertura de techo"
    CIERRE_TECHO = "Cierre de techo"
    APERTURA_CORTINAS = "Apertura de cortinas"
    CIERRE_CORTINAS = "Cierre de cortinas"
    VENTILADORES = "Encender ventiladores"


class EstadoTecho(str, Enum):
    ABIERTO = "abierto"
    CERRADO = "cerrado"


class EstadoCortinas(str, Enum):
    ABIERTAS = "abiertas"
    CERRADAS = "cerradas"


# =========================================================================== #
# 2. Configuración
# =========================================================================== #
# DJANGO: un modelo ConfiguracionInvernadero con estos campos (o un JSONField).
@dataclass
class ConfigInvernadero:
    # --- Exterior y ciclo diario -------------------------------------------
    temp_base_exterior: float = 20.0       # °C de día, sin eventos
    descenso_nocturno: float = 7.5         # °C que baja el exterior de noche
    hora_amanecer: float = 6.5             # horas decimales (6.5 = 06:30)
    hora_atardecer: float = 19.5
    crepusculo_h: float = 1.0              # duración de la transición día/noche
    rad_max_exterior: float = 900.0        # W/m² al mediodía solar, cielo despejado

    # --- Interior y retardo respecto al exterior ---------------------------
    temp_interna_inicial: float | None = None   # None = igual al exterior inicial
    tau_retardo_base_s: float = 3600.0     # tau con techo y cortinas CERRADOS (caso más lento), en s simulados
    tau_actuadores_s: float = 120.0        # transición suave al cambiar el factor de retardo

    transmision_techo_abierto: float = 0.90
    transmision_techo_cerrado: float = 0.70

    # Multiplicadores del retardo (> 1.0 aumenta el retardo; < 1.0 lo reduce = el interior
    # alcanza antes la temperatura exterior). Con los valores por defecto:
    #   cerrado/cerrado: t90 ~ 2.3 h | cortinas abiertas: ~48 min | cortinas + techo abiertos: ~15 min
    retardo_techo_abierto: float = 0.31
    retardo_techo_cerrado: float = 1.0
    retardo_cortinas_abiertas: float = 0.35
    retardo_cortinas_cerradas: float = 1.0

    # Ventiladores: enfriamiento directo, independiente del retardo y del clima
    enfriamiento_ventiladores: float = 0.15   # fracción de la temperatura interior que restan (0.15 = 15 %)
    tau_ventiladores_s: float = 300.0         # lo que tardan en alcanzar (o perder) su efecto, en s simulados

    # Estado por defecto cuando NO hay ningún evento activo: todo desactivado/cerrado.
    techo_por_defecto: EstadoTecho = EstadoTecho.CERRADO
    cortinas_por_defecto: EstadoCortinas = EstadoCortinas.CERRADAS

    # --- Simulación --------------------------------------------------------
    max_paso_s: float = 120.0              # paso máximo de integración (s simulados)
    velocidad_max: float = 100_000.0       # tope del multiplicador de tiempo

    def __post_init__(self) -> None:
        if not 0 <= self.hora_amanecer < self.hora_atardecer <= 24:
            raise ValueError("Se requiere 0 <= hora_amanecer < hora_atardecer <= 24.")
        if self.tau_retardo_base_s <= 0 or self.max_paso_s <= 0:
            raise ValueError("tau_retardo_base_s y max_paso_s deben ser > 0.")


# =========================================================================== #
# 3. Eventos
# =========================================================================== #
def _suave(x: float) -> float:
    """Rampa suave (smoothstep) de 0 a 1."""
    x = 0.0 if x < 0.0 else 1.0 if x > 1.0 else x
    return x * x * (3.0 - 2.0 * x)


class EfectoClima(NamedTuple):
    """Efecto *máximo* de un evento climático sobre el exterior y sobre el retardo interior."""
    delta_temp: float          # °C que suma al exterior
    factor_rad: float          # multiplica la radiación solar (1.0 = sin cambio)
    factor_retardo: float = 1.0  # multiplica el retardo de temperatura interior (1.0 = sin cambio)
    solo_de_dia: bool = False  # si True, el delta_temp se atenúa de noche


# DJANGO: tabla de datos/fixture si se quiere editar desde el admin.
PERFILES_CLIMA: dict[TipoClima, EfectoClima] = {
    TipoClima.SOL_INTENSO:        EfectoClima(+8.0,  1.25, factor_retardo=0.90, solo_de_dia=True),
    TipoClima.NUBLADO:            EfectoClima(-2.0,  0.40, factor_retardo=1.05),
    TipoClima.LLUVIA:             EfectoClima(-3.5,  0.25, factor_retardo=1.30),
    TipoClima.TORMENTA_ELECTRICA: EfectoClima(-5.0,  0.12, factor_retardo=1.45),
    TipoClima.TORMENTA:           EfectoClima(-4.0,  0.20, factor_retardo=1.35),
    TipoClima.FRIO_INTENSO:       EfectoClima(-12.0, 0.90, factor_retardo=1.20),
}


# DJANGO: modelo abstracto EventoProgramado (inicio, fin, transicion_s) y dos modelos hijos.
@dataclass(kw_only=True)
class EventoProgramado:
    """Evento agendado con inicio y fin (fin=None => dura hasta que otro evento lo reemplace/cancele)."""
    inicio: datetime
    fin: datetime | None = None
    transicion_s: float = 0.0          # rampa de entrada y de salida
    id: int | None = None              # lo asigna la Agenda (en Django: la pk)

    def __post_init__(self) -> None:
        if self.fin is not None and self.fin <= self.inicio:
            raise ValueError("fin debe ser posterior a inicio.")
        if self.transicion_s < 0:
            raise ValueError("transicion_s no puede ser negativa.")

    @property
    def nombre(self) -> str:  # pragma: no cover - lo implementan los hijos
        raise NotImplementedError

    def activo_en(self, t: datetime) -> bool:
        return self.inicio <= t and (self.fin is None or t < self.fin)

    def nivel(self, t: datetime) -> float:
        """Intensidad entre 0 y 1: rampa de subida, meseta y rampa de bajada. Los eventos se pueden solapar."""
        if t < self.inicio:
            return 0.0
        r = self.transicion_s
        if r > 0:
            subida = _suave((t - self.inicio).total_seconds() / r)
            bajada = 1.0 if self.fin is None else 1.0 - _suave((t - self.fin).total_seconds() / r)
        else:
            subida = 1.0
            bajada = 1.0 if (self.fin is None or t < self.fin) else 0.0
        return min(subida, bajada)


@dataclass(kw_only=True)
class EventoClimatico(EventoProgramado):
    tipo: TipoClima
    transicion_s: float = 20 * 60.0    # los cambios de clima son graduales (20 min por defecto)

    @property
    def nombre(self) -> str:
        return self.tipo.value


@dataclass(kw_only=True)
class EventoInterior(EventoProgramado):
    accion: AccionInterior

    @property
    def nombre(self) -> str:
        return self.accion.value


class Agenda:
    """Colección thread-safe de eventos. Se pueden agregar/cancelar mientras el simulador corre."""

    # DJANGO: reemplazar por consultas al ORM (EventoClimatico.objects.filter(invernadero=...)).
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._eventos: list[EventoProgramado] = []
        self._siguiente_id = 1

    def agregar(self, evento: EventoProgramado) -> EventoProgramado:
        with self._lock:
            evento.id = self._siguiente_id
            self._siguiente_id += 1
            self._eventos.append(evento)
        return evento

    def cancelar(self, evento_id: int) -> bool:
        with self._lock:
            antes = len(self._eventos)
            self._eventos = [e for e in self._eventos if e.id != evento_id]
            return len(self._eventos) != antes

    def limpiar(self) -> None:
        with self._lock:
            self._eventos.clear()

    def todos(self) -> list[EventoProgramado]:
        with self._lock:
            return list(self._eventos)

    def snapshot(self) -> tuple[list[EventoClimatico], list[EventoInterior]]:
        with self._lock:
            return (
                [e for e in self._eventos if isinstance(e, EventoClimatico)],
                [e for e in self._eventos if isinstance(e, EventoInterior)],
            )


# =========================================================================== #
# 4. Reloj simulado
# =========================================================================== #
class RelojSimulado:
    """
    Convierte tiempo real en tiempo simulado. La velocidad se puede cambiar en cualquier momento
    desde cualquier hilo.   1 = tiempo real | 60 = 1 min/s | 3600 = 1 h/s | 86400 = 1 día/s
    """

    def __init__(self, velocidad: float = 60.0, velocidad_max: float = 100_000.0) -> None:
        self._lock = threading.Lock()
        self._velocidad_max = velocidad_max
        self._velocidad = 1.0
        self._pausado = False
        self._ultimo = time.monotonic()
        self.seg_reales = 0.0        # tiempo real transcurrido simulando (sin contar pausas)
        self.seg_simulados = 0.0
        self.velocidad = velocidad

    @property
    def velocidad(self) -> float:
        return self._velocidad

    @velocidad.setter
    def velocidad(self, valor: float) -> None:
        if valor <= 0:
            raise ValueError("La velocidad debe ser > 0 (para frenar usá pausar()).")
        with self._lock:
            self._velocidad = min(float(valor), self._velocidad_max)

    @property
    def pausado(self) -> bool:
        return self._pausado

    def pausar(self) -> None:
        with self._lock:
            self._pausado = True

    def reanudar(self) -> None:
        with self._lock:
            self._ultimo = time.monotonic()
            self._pausado = False

    def resincronizar(self) -> None:
        """Descarta el tiempo real acumulado desde el último tick (al arrancar el hilo)."""
        with self._lock:
            self._ultimo = time.monotonic()

    def tick(self, max_real_s: float = 1.0) -> float:
        """Devuelve cuántos segundos simulados pasaron desde el tick anterior."""
        with self._lock:
            ahora = time.monotonic()
            real = min(ahora - self._ultimo, max_real_s)   # tope: evita saltos si el proceso se congela
            self._ultimo = ahora
            if self._pausado:
                return 0.0
            sim = real * self._velocidad
            self.seg_reales += real
            self.seg_simulados += sim
            return sim

    def adelantar(self, seg_simulados: float) -> None:
        """Contabiliza un avance manual (ver Simulador.avanzar)."""
        with self._lock:
            self.seg_simulados += seg_simulados
            self.seg_reales += seg_simulados / self._velocidad


# =========================================================================== #
# 5. Modelos físicos
# =========================================================================== #
class EstadoExterior(NamedTuple):
    temp: float            # °C
    rad: float             # W/m²
    factor_retardo: float = 1.0  # multiplicador de retardo aportado por eventos climáticos


class CicloDiario:
    """Día de 24 h: noche, amanecer/atardecer y radiación solar base."""

    def __init__(self, cfg: ConfigInvernadero) -> None:
        self.cfg = cfg

    @staticmethod
    def hora_decimal(t: datetime) -> float:
        return t.hour + t.minute / 60.0 + t.second / 3600.0 + t.microsecond / 3.6e9

    def factor_noche(self, t: datetime) -> float:
        """0 = pleno día, 1 = noche cerrada, con crepúsculo suave en amanecer y atardecer."""
        c = max(self.cfg.crepusculo_h, 1e-6)
        h = self.hora_decimal(t)
        sube = _suave((h - (self.cfg.hora_amanecer - c / 2)) / c)
        baja = _suave(((self.cfg.hora_atardecer + c / 2) - h) / c)
        return 1.0 - min(sube, baja)

    def radiacion_solar(self, t: datetime) -> float:
        """Arco senoidal entre amanecer y atardecer; 0 de noche."""
        h = self.hora_decimal(t)
        a, b = self.cfg.hora_amanecer, self.cfg.hora_atardecer
        if not a <= h < b:
            return 0.0
        return self.cfg.rad_max_exterior * math.sin(math.pi * (h - a) / (b - a))

    def noches_entre(self, desde: datetime, hasta: datetime) -> list[tuple[datetime, datetime]]:
        """Intervalos (atardecer -> amanecer siguiente) que tocan [desde, hasta]. Útil para graficar."""
        dia = datetime.combine(desde.date() - timedelta(days=1), datetime.min.time())
        salida = []
        while dia <= hasta:
            ini = dia + timedelta(hours=self.cfg.hora_atardecer)
            fin = dia + timedelta(days=1, hours=self.cfg.hora_amanecer)
            if fin >= desde and ini <= hasta:
                salida.append((ini, fin))
            dia += timedelta(days=1)
        return salida


class ClimaExterior:
    """Temperatura, radiación y factor de retardo climático en el exterior."""

    def __init__(self, cfg: ConfigInvernadero, ciclo: CicloDiario) -> None:
        self.cfg = cfg
        self.ciclo = ciclo

    def calcular(self, t: datetime, eventos: list[EventoClimatico]) -> EstadoExterior:
        noche = self.ciclo.factor_noche(t)
        temp = self.cfg.temp_base_exterior - self.cfg.descenso_nocturno * noche
        factor_rad = 1.0
        factor_retardo = 1.0
        for ev in eventos:
            n = ev.nivel(t)
            if n <= 0.0:
                continue
            ef = PERFILES_CLIMA[ev.tipo]
            d_temp = ef.delta_temp * n
            if ef.solo_de_dia:
                d_temp *= (1.0 - noche)
            temp += d_temp
            factor_rad *= 1.0 + (ef.factor_rad - 1.0) * n
            factor_retardo *= 1.0 + (ef.factor_retardo - 1.0) * n
        return EstadoExterior(temp, max(0.0, self.ciclo.radiacion_solar(t) * factor_rad), factor_retardo)


class Invernadero:
    """
    Interior: su temperatura tiene un comportamiento retardado respecto a la temperatura exterior,
    y los eventos (techo, cortinas y clima) modifican cuánto se retarda. Los ventiladores no
    tocan el retardo: restan directamente un % a la temperatura interior.
    """

    def __init__(self, cfg: ConfigInvernadero, temp_inicial: float) -> None:
        self.cfg = cfg
        self._temp_lag = temp_inicial          # temperatura interior SIN ventiladores (sigue al exterior con retardo)
        self._nivel_vent = 0.0                 # 0 = apagados, 1 = enfriando a pleno (se suaviza)
        self.rad_interna = 0.0
        self.techo = cfg.techo_por_defecto
        self.cortinas = cfg.cortinas_por_defecto
        self.ventiladores = False
        self._ext_temp = temp_inicial
        self.ids_vigentes: set[int] = set()
        self._trans, self._factor_retardo_actuadores = self._objetivos()
        self._factor_retardo_efectivo = self._factor_retardo_actuadores

    # -- estados --------------------------------------------------------- #
    @staticmethod
    def _vigente(t: datetime, eventos: list[EventoInterior],
                 a: AccionInterior, b: AccionInterior) -> EventoInterior | None:
        """Entre los eventos activos `a`/`b`, gana el que empezó más recientemente."""
        mejor: EventoInterior | None = None
        for ev in eventos:
            if ev.accion in (a, b) and ev.activo_en(t):
                if mejor is None or (ev.inicio, ev.id or 0) > (mejor.inicio, mejor.id or 0):
                    mejor = ev
        return mejor

    def _resolver_estados(self, t: datetime, eventos: list[EventoInterior]) -> None:
        ev_techo = self._vigente(t, eventos, AccionInterior.APERTURA_TECHO, AccionInterior.CIERRE_TECHO)
        estado_techo_ev = (
            None if ev_techo is None else
            EstadoTecho.ABIERTO if ev_techo.accion == AccionInterior.APERTURA_TECHO
            else EstadoTecho.CERRADO
        )
        if estado_techo_ev is None or estado_techo_ev == self.cfg.techo_por_defecto:
            self.techo = self.cfg.techo_por_defecto
            techo_id = None
        else:
            self.techo = estado_techo_ev
            techo_id = ev_techo.id

        ev_cort = self._vigente(t, eventos, AccionInterior.APERTURA_CORTINAS, AccionInterior.CIERRE_CORTINAS)
        estado_cort_ev = (
            None if ev_cort is None else
            EstadoCortinas.ABIERTAS if ev_cort.accion == AccionInterior.APERTURA_CORTINAS
            else EstadoCortinas.CERRADAS
        )
        if estado_cort_ev is None or estado_cort_ev == self.cfg.cortinas_por_defecto:
            self.cortinas = self.cfg.cortinas_por_defecto
            cort_id = None
        else:
            self.cortinas = estado_cort_ev
            cort_id = ev_cort.id

        self.ids_vigentes = {eid for eid in (techo_id, cort_id) if eid is not None}

        self.ventiladores = any(
            ev.accion == AccionInterior.VENTILADORES and ev.activo_en(t) for ev in eventos
        )

    def _objetivos(self) -> tuple[float, float]:
        c = self.cfg
        abierto = self.techo == EstadoTecho.ABIERTO
        trans = c.transmision_techo_abierto if abierto else c.transmision_techo_cerrado
        ret_techo = c.retardo_techo_abierto if abierto else c.retardo_techo_cerrado
        ret_cort = (
            c.retardo_cortinas_abiertas
            if self.cortinas == EstadoCortinas.ABIERTAS
            else c.retardo_cortinas_cerradas
        )
        return trans, max(0.05, ret_techo * ret_cort)

    # -- física ---------------------------------------------------------- #
    @property
    def temp_objetivo(self) -> float:
        """Temperatura de referencia hacia la que tiende con retardo la temperatura interior."""
        return self._ext_temp

    @property
    def tau_retardo_actual_s(self) -> float:
        """Constante de retardo efectiva (en segundos simulados) tras aplicar eventos."""
        return max(1e-3, self.cfg.tau_retardo_base_s * self._factor_retardo_efectivo)

    @property
    def temp_interna(self) -> float:
        """Temperatura interior = la que tendría sin ventiladores menos el enfriamiento de los ventiladores."""
        return self._temp_lag - self.cfg.enfriamiento_ventiladores * abs(self._temp_lag) * self._nivel_vent

    @temp_interna.setter
    def temp_interna(self, valor: float) -> None:
        self._temp_lag = valor                 # asignación manual: se toma como temperatura base

    @property
    def t90_s(self) -> float:
        """Segundos simulados que tardaría el interior en cubrir el 90 % de la diferencia con el exterior."""
        return self.tau_retardo_actual_s * math.log(10.0)

    def paso(self, dt: float, t: datetime, ext: EstadoExterior,
             eventos: list[EventoInterior]) -> None:
        self._ext_temp = ext.temp
        self._resolver_estados(t, eventos)

        # 1) Los actuadores y eventos modifican el retardo de forma gradual
        k = 1.0 - math.exp(-dt / max(self.cfg.tau_actuadores_s, 1e-6))
        o_trans, o_ret_act = self._objetivos()
        self._trans += (o_trans - self._trans) * k
        self._factor_retardo_actuadores += (o_ret_act - self._factor_retardo_actuadores) * k

        factor_ret_objetivo = max(0.05, self._factor_retardo_actuadores * ext.factor_retardo)
        self._factor_retardo_efectivo += (factor_ret_objetivo - self._factor_retardo_efectivo) * k

        # 2) Radiación interior
        self.rad_interna = ext.rad * self._trans

        # 3) Temperatura interior: sigue a la exterior con retardo gobernado por tau_retardo_actual_s
        k_t = 1.0 - math.exp(-dt / self.tau_retardo_actual_s)
        self._temp_lag += (self.temp_objetivo - self._temp_lag) * k_t

        # 4) Ventiladores: enfriamiento directo (no pasa por el retardo ni depende del clima)
        k_v = 1.0 - math.exp(-dt / max(self.cfg.tau_ventiladores_s, 1e-6))
        self._nivel_vent += ((1.0 if self.ventiladores else 0.0) - self._nivel_vent) * k_v


# =========================================================================== #
# 6. Mediciones e historial
# =========================================================================== #
# DJANGO: modelo Medicion (mismos campos) + índice en `instante`.
@dataclass(frozen=True)
class Medicion:
    instante: datetime
    seg_simulados: float
    seg_reales: float
    velocidad: float
    pausado: bool
    temp_externa: float
    temp_interna: float
    rad_externa: float
    rad_interna: float
    techo: EstadoTecho
    cortinas: EstadoCortinas
    ventiladores: bool
    eventos_activos: tuple[str, ...]

    @property
    def resumen_tiempo(self) -> str:
        pausa = " (PAUSA)" if self.pausado else ""
        return (f"{self.instante:%d/%m/%Y %H:%M} | {self.seg_reales:.0f} s reales | "
                f"x{self.velocidad:g}{pausa}")

    def como_dict(self) -> dict:
        """Serializable a JSON (para JsonResponse / WebSocket en Django)."""
        return {
            "instante": self.instante.isoformat(),
            "seg_simulados": self.seg_simulados,
            "seg_reales": self.seg_reales,
            "velocidad": self.velocidad,
            "pausado": self.pausado,
            "temp_externa": round(self.temp_externa, 3),
            "temp_interna": round(self.temp_interna, 3),
            "rad_externa": round(self.rad_externa, 2),
            "rad_interna": round(self.rad_interna, 2),
            "techo": self.techo.value,
            "cortinas": self.cortinas.value,
            "ventiladores": self.ventiladores,
            "eventos_activos": list(self.eventos_activos),
        }


class Historial:
    """Buffer circular thread-safe de mediciones."""

    # DJANGO: Medicion.objects.bulk_create(...) cada N registros y consultas por rango de fechas.
    def __init__(self, maxlen: int = 200_000) -> None:
        self._lock = threading.Lock()
        self._datos: deque[Medicion] = deque(maxlen=maxlen)

    def agregar(self, m: Medicion) -> None:
        with self._lock:
            self._datos.append(m)

    def desde(self, instante: datetime | None = None) -> list[Medicion]:
        with self._lock:
            if instante is None:
                return list(self._datos)
            salida = []
            for m in reversed(self._datos):
                if m.instante < instante:
                    break
                salida.append(m)
        salida.reverse()
        return salida

    def __len__(self) -> int:
        return len(self._datos)


# =========================================================================== #
# 7. Simulador (orquestador)
# =========================================================================== #
class Simulador:
    """
    Corre en un hilo propio. Desde afuera (consola, otro hilo, una vista de Django) se puede:
        sim.velocidad = 3600            # cambiar el ritmo del tiempo en caliente
        sim.pausar() / sim.reanudar()
        sim.programar_clima(...)        # agendar eventos con inicio y fin
        sim.clima_ahora(...)            # o dispararlos ya
        sim.medicion_actual()           # leer el estado
    """

    def __init__(
        self,
        cfg: ConfigInvernadero | None = None,
        inicio: datetime | None = None,
        velocidad: float = 60.0,
        tick_real_s: float = 0.05,          # cada cuánto despierta el hilo
        intervalo_registro_s: float = 60.0,  # resolución del historial (segundos simulados)
    ) -> None:
        self.cfg = cfg or ConfigInvernadero()
        # DJANGO: usar timezone.now() si USE_TZ=True.
        self.inicio = inicio or datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)

        self.reloj = RelojSimulado(velocidad, self.cfg.velocidad_max)
        self.agenda = Agenda()
        self.ciclo = CicloDiario(self.cfg)
        self.exterior = ClimaExterior(self.cfg, self.ciclo)
        self.historial = Historial()

        self._tick_real_s = tick_real_s
        self._intervalo_registro_s = intervalo_registro_s
        self._seg_modelo = 0.0                 # segundos simulados ya integrados
        self._seg_desde_registro = 0.0
        self._lock = threading.RLock()
        self._detener = threading.Event()
        self._hilo: threading.Thread | None = None

        # Estado inicial coherente (sin transitorios al arrancar)
        self._ext = self.exterior.calcular(self.inicio, [])
        t_ini = self.cfg.temp_interna_inicial
        self.invernadero = Invernadero(self.cfg, self._ext.temp if t_ini is None else t_ini)
        self.invernadero._ext_temp = self._ext.temp
        self.historial.agregar(self._medir(self.inicio))

    # -- ciclo de vida --------------------------------------------------- #
    def iniciar(self) -> None:
        if self.corriendo:
            return
        self._detener.clear()
        self.reloj.resincronizar()
        self._hilo = threading.Thread(target=self._bucle, name="simulador-invernadero", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._detener.set()
        if self._hilo and self._hilo is not threading.current_thread():
            self._hilo.join(timeout=2.0)
        self._hilo = None

    @property
    def corriendo(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def __enter__(self) -> "Simulador":
        self.iniciar()
        return self

    def __exit__(self, *exc) -> None:
        self.detener()

    def _bucle(self) -> None:
        while not self._detener.is_set():
            delta = self.reloj.tick()
            if delta > 0.0:
                self._integrar(delta)
            self._detener.wait(self._tick_real_s)

    # -- control del tiempo --------------------------------------------- #
    @property
    def velocidad(self) -> float:
        return self.reloj.velocidad

    @velocidad.setter
    def velocidad(self, valor: float) -> None:
        self.reloj.velocidad = valor

    @property
    def pausado(self) -> bool:
        return self.reloj.pausado

    def pausar(self) -> None:
        self.reloj.pausar()

    def reanudar(self) -> None:
        self.reloj.reanudar()

    @property
    def instante(self) -> datetime:
        """Fecha y hora simuladas actuales."""
        return self.inicio + timedelta(seconds=self._seg_modelo)

    def avanzar(self, seg_simulados: float) -> Medicion:
        """Avance manual sin esperar tiempo real (tests, scripts, tareas por lotes)."""
        self.reloj.adelantar(seg_simulados)
        self._integrar(seg_simulados)
        return self.medicion_actual()

    # -- eventos ---------------------------------------------------------- #
    # DJANGO: estos métodos pasan a ser vistas/serializers que crean filas en la BD.
    def programar_clima(self, tipo: TipoClima, inicio: datetime, fin: datetime | None = None,
                        transicion_s: float | None = None) -> EventoClimatico:
        extra = {} if transicion_s is None else {"transicion_s": transicion_s}
        return self.agenda.agregar(EventoClimatico(tipo=tipo, inicio=inicio, fin=fin, **extra))

    def programar_accion(self, accion: AccionInterior, inicio: datetime,
                         fin: datetime | None = None) -> EventoInterior:
        return self.agenda.agregar(EventoInterior(accion=accion, inicio=inicio, fin=fin))

    def clima_ahora(self, tipo: TipoClima, duracion_h: float | None = 2.0) -> EventoClimatico:
        ini = self.instante
        fin = None if duracion_h is None else ini + timedelta(hours=duracion_h)
        return self.programar_clima(tipo, ini, fin)

    def accion_ahora(self, accion: AccionInterior, duracion_h: float | None = None) -> EventoInterior:
        ini = self.instante
        fin = None if duracion_h is None else ini + timedelta(hours=duracion_h)
        return self.programar_accion(accion, ini, fin)

    def cancelar_evento(self, evento_id: int) -> bool:
        return self.agenda.cancelar(evento_id)

    # -- lectura de estado ------------------------------------------------ #
    _ACCIONES_DE_ESTADO = frozenset({
        AccionInterior.APERTURA_TECHO, AccionInterior.CIERRE_TECHO,
        AccionInterior.APERTURA_CORTINAS, AccionInterior.CIERRE_CORTINAS,
    })

    def evento_vigente(self, ev: EventoProgramado, t: datetime | None = None) -> bool:
        """Activo y no pisado por un evento de estado más reciente ni redundante con el defecto."""
        if not ev.activo_en(t or self.instante):
            return False
        if isinstance(ev, EventoInterior) and ev.accion in self._ACCIONES_DE_ESTADO:
            return ev.id in self.invernadero.ids_vigentes
        return True

    def medicion_actual(self) -> Medicion:
        with self._lock:
            return self._medir(self.instante)

    # -- internos ---------------------------------------------------------- #
    def _integrar(self, seg: float) -> None:
        """Avanza el modelo `seg` segundos simulados en pasos de a lo sumo max_paso_s."""
        with self._lock:
            climaticos, interiores = self.agenda.snapshot()
            restante = seg
            while restante > 1e-9:
                dt = min(restante, self.cfg.max_paso_s)
                self._seg_modelo += dt
                t = self.inicio + timedelta(seconds=self._seg_modelo)

                self._ext = self.exterior.calcular(t, climaticos)    # 1) exterior (independiente)
                self.invernadero.paso(dt, t, self._ext, interiores)  # 2) interior (depende del exterior)

                self._seg_desde_registro += dt
                if self._seg_desde_registro >= self._intervalo_registro_s:
                    self._seg_desde_registro = 0.0
                    self.historial.agregar(self._medir(t))
                restante -= dt

    def _medir(self, t: datetime) -> Medicion:
        inv = self.invernadero
        activos = tuple(dict.fromkeys(e.nombre for e in self.agenda.todos() if self.evento_vigente(e, t)))
        return Medicion(
            instante=t,
            seg_simulados=self._seg_modelo,
            seg_reales=self.reloj.seg_reales,
            velocidad=self.reloj.velocidad,
            pausado=self.reloj.pausado,
            temp_externa=self._ext.temp,
            temp_interna=inv.temp_interna,
            rad_externa=self._ext.rad,
            rad_interna=inv.rad_interna,
            techo=inv.techo,
            cortinas=inv.cortinas,
            ventiladores=inv.ventiladores,
            eventos_activos=activos,
        )


# =========================================================================== #
# 8. Visualizador (matplotlib)
# =========================================================================== #
class Visualizador:
    """
    Solo LEE del simulador (medicion_actual, historial, agenda) y le manda órdenes simples
    (velocidad, pausa, eventos). No contiene lógica física.
    DJANGO: este módulo no se migra; lo reemplaza el front consumiendo Medicion.como_dict().

    Controles: slider de velocidad, botones de pausa/eventos, y teclado: ESPACIO = pausa,
    flecha arriba/abajo = velocidad x2 / x0.5.
    """

    COLORES = {
        TipoClima.SOL_INTENSO: "#f4b400",
        TipoClima.NUBLADO: "#9aa0a6",
        TipoClima.LLUVIA: "#4285f4",
        TipoClima.TORMENTA_ELECTRICA: "#9334e6",
        TipoClima.TORMENTA: "#5f6368",
        TipoClima.FRIO_INTENSO: "#00acc1",
        AccionInterior.APERTURA_TECHO: "#34a853",
        AccionInterior.CIERRE_TECHO: "#188038",
        AccionInterior.APERTURA_CORTINAS: "#fa7b17",
        AccionInterior.CIERRE_CORTINAS: "#b06000",
        AccionInterior.VENTILADORES: "#12b5cb",
    }
    C_EXT, C_INT = "tab:orange", "tab:blue"

    def __init__(self, sim: Simulador, ventana_horas: float = 48.0,
                 intervalo_ms: int = 100, duracion_evento_h: float = 3.0) -> None:
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
        from matplotlib.colors import to_rgb
        from matplotlib.patches import Rectangle
        from matplotlib.widgets import Button, Slider

        self._mdates, self._plt = mdates, plt
        self._Rectangle, self._Button, self._to_rgb = Rectangle, Button, to_rgb

        self.sim = sim
        self.ventana = timedelta(hours=ventana_horas)
        self.duracion_evento_h = duracion_evento_h
        self._widgets: list = []                      # referencias para que no los recoja el GC
        self._rects: dict[int, object] = {}           # id de evento -> rectángulo del Gantt
        self._noches: dict[datetime, list] = {}

        self._carriles = list(TipoClima) + list(AccionInterior)
        self._carril = {k: i for i, k in enumerate(self._carriles)}

        # ---- ejes -------------------------------------------------------
        self.fig = plt.figure(figsize=(14.5, 8.5))
        self.fig.canvas.manager.set_window_title("Simulador de invernadero") if self.fig.canvas.manager else None
        L, W = 0.13, 0.61
        self.ax_t = self.fig.add_axes([L, 0.62, W, 0.33])
        self.ax_r = self.fig.add_axes([L, 0.39, W, 0.21], sharex=self.ax_t)
        self.ax_g = self.fig.add_axes([L, 0.07, W, 0.28], sharex=self.ax_t)
        self.ax_t.xaxis_date()
        for ax in (self.ax_t, self.ax_r):
            ax.tick_params(labelbottom=False)
        for ax in (self.ax_t, self.ax_r, self.ax_g):
            ax.grid(alpha=0.3)

        self.l_t_ext, = self.ax_t.plot([], [], color=self.C_EXT, lw=1.8, label="Exterior")
        self.l_t_int, = self.ax_t.plot([], [], color=self.C_INT, lw=1.8, label="Interior")
        self.l_r_ext, = self.ax_r.plot([], [], color=self.C_EXT, lw=1.8, label="Exterior")
        self.l_r_int, = self.ax_r.plot([], [], color=self.C_INT, lw=1.8, label="Interior")
        self.ax_t.set_ylabel("Temperatura (°C)")
        self.ax_r.set_ylabel("Radiación (W/m²)")
        self.ax_t.legend(loc="upper left", fontsize=8)
        self.ax_r.legend(loc="upper left", fontsize=8)

        self._l_ahora = [ax.axvline(0, color="k", lw=0.8, ls="--")
                         for ax in (self.ax_t, self.ax_r, self.ax_g)]

        self.ax_g.set_yticks(range(len(self._carriles)))
        self.ax_g.set_yticklabels([c.value for c in self._carriles], fontsize=8)
        self.ax_g.set_ylim(len(self._carriles) - 0.5, -0.5)
        self.ax_g.set_title("Agenda de eventos (rayado = sin fin definido)", fontsize=8, loc="left")
        loc = mdates.AutoDateLocator(minticks=4, maxticks=10)
        self.ax_g.xaxis.set_major_locator(loc)
        self.ax_g.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))

        self._crear_controles(Slider)
        self.fig.canvas.mpl_connect("key_press_event", self._tecla)
        self.anim = FuncAnimation(self.fig, self._actualizar, interval=intervalo_ms,
                                  cache_frame_data=False)

    # ------------------------------------------------------------------ #
    # Controles
    # ------------------------------------------------------------------ #
    def _pastel(self, color: str, f: float = 0.65):
        return tuple(c + (1.0 - c) * f for c in self._to_rgb(color))

    def _boton(self, rect, texto, color, callback) -> None:
        ax = self.fig.add_axes(rect)
        b = self._Button(ax, texto, color=self._pastel(color), hovercolor=self._pastel(color, 0.3))
        b.label.set_fontsize(8)
        b.on_clicked(callback)
        self._widgets.append(b)

    def _crear_controles(self, Slider) -> None:
        f, x, w, h = self.fig, 0.79, 0.185, 0.036
        self._txt = f.text(x, 0.985, "", va="top", fontsize=8, family="monospace")

        f.text(x, 0.835, "Velocidad del tiempo (1x a máx.)", fontsize=8)
        ax_s = f.add_axes([x, 0.805, 0.13, 0.02])
        vmax = math.log10(self.sim.cfg.velocidad_max)
        self.slider = Slider(ax_s, "", 0.0, vmax, valinit=self._log_vel(), color="0.6")
        self.slider.vline.set_visible(False)           # oculta la marca roja del valor inicial
        self.slider.on_changed(self._al_mover_slider)
        self._texto_slider(self.sim.velocidad)

        self._btn_pausa_ax = f.add_axes([x, 0.745, 0.09, h])
        self._btn_pausa = self._Button(self._btn_pausa_ax, "Pausar", color="0.9", hovercolor="0.8")
        self._btn_pausa.label.set_fontsize(8)
        self._btn_pausa.on_clicked(lambda _e: self._alternar_pausa())
        self._widgets.append(self._btn_pausa)
        self._boton([x + 0.095, 0.745, 0.09, h], "Limpiar agenda", "#d93025",
                    lambda _e: self.sim.agenda.limpiar())

        f.text(x, 0.70, f"Clima exterior (ahora, {self.duracion_evento_h:g} h)", fontsize=8)
        y = 0.66
        for tipo in TipoClima:
            self._boton([x, y, 0.185, h], tipo.value, self.COLORES[tipo],
                        partial(self._disparar_clima, tipo))
            y -= 0.044

        f.text(x, y + 0.004, "Invernadero (ahora)", fontsize=8)
        y -= 0.036
        for accion in AccionInterior:
            self._boton([x, y, 0.185, h], accion.value, self.COLORES[accion],
                        partial(self._disparar_accion, accion))
            y -= 0.044

    def _disparar_clima(self, tipo: TipoClima, _evento=None) -> None:
        self.sim.clima_ahora(tipo, self.duracion_evento_h)

    def _disparar_accion(self, accion: AccionInterior, _evento=None) -> None:
        dur = self.duracion_evento_h if accion == AccionInterior.VENTILADORES else None
        self.sim.accion_ahora(accion, dur)

    def _alternar_pausa(self) -> None:
        self.sim.reanudar() if self.sim.pausado else self.sim.pausar()

    def _log_vel(self) -> float:
        return math.log10(max(1.0, self.sim.velocidad))

    def _texto_slider(self, v: float) -> None:
        self.slider.valtext.set_text(f"x{v:,.0f}")

    def _al_mover_slider(self, val: float) -> None:
        v = 10.0 ** val
        self.sim.velocidad = v
        self._texto_slider(v)

    def _tecla(self, ev) -> None:
        if ev.key == " ":
            self._alternar_pausa()
        elif ev.key == "up":
            self.sim.velocidad = self.sim.velocidad * 2
        elif ev.key == "down":
            self.sim.velocidad = max(1.0, self.sim.velocidad / 2)

    # ------------------------------------------------------------------ #
    # Dibujo
    # ------------------------------------------------------------------ #
    def _actualizar(self, _frame=None) -> None:
        sim, d2n = self.sim, self._mdates.date2num
        m = sim.medicion_actual()
        ahora = m.instante
        derecha = ahora + self.ventana * 0.25          # se deja un margen a futuro para ver lo agendado
        izquierda = derecha - self.ventana
        if izquierda < sim.inicio:                     # al arrancar: ventana fija desde el inicio
            izquierda, derecha = sim.inicio, sim.inicio + self.ventana

        hist = sim.historial.desde(izquierda)
        if not hist or hist[-1].instante < ahora:
            hist.append(m)
        xs = d2n([h.instante for h in hist])
        t_ext = [h.temp_externa for h in hist]
        t_int = [h.temp_interna for h in hist]
        r_ext = [h.rad_externa for h in hist]
        r_int = [h.rad_interna for h in hist]
        self.l_t_ext.set_data(xs, t_ext)
        self.l_t_int.set_data(xs, t_int)
        self.l_r_ext.set_data(xs, r_ext)
        self.l_r_int.set_data(xs, r_int)

        self.ax_t.set_xlim(d2n(izquierda), d2n(derecha))
        self.ax_t.set_ylim(min(t_ext + t_int) - 2.0, max(t_ext + t_int) + 2.0)
        self.ax_r.set_ylim(0.0, max(300.0, max(r_ext + r_int) * 1.1))
        for ln in self._l_ahora:
            ln.set_xdata([d2n(ahora)] * 2)

        self._dibujar_noches(izquierda, derecha)
        self._dibujar_agenda(ahora, d2n(derecha))
        self._escribir_estado(m)
        self._sincronizar_controles()

    def _dibujar_noches(self, izq: datetime, der: datetime) -> None:
        d2n = self._mdates.date2num
        vigentes = set()
        for ini, fin in self.sim.ciclo.noches_entre(izq, der):
            vigentes.add(ini)
            if ini not in self._noches:
                self._noches[ini] = [
                    ax.axvspan(d2n(ini), d2n(fin), color="0.5", alpha=0.15, lw=0)
                    for ax in (self.ax_t, self.ax_r, self.ax_g)
                ]
        for ini in [k for k in self._noches if k not in vigentes]:
            for parche in self._noches.pop(ini):
                parche.remove()

    def _dibujar_agenda(self, ahora: datetime, x_der: float) -> None:
        d2n = self._mdates.date2num
        vivos = set()
        for ev in self.sim.agenda.todos():
            clave = ev.tipo if isinstance(ev, EventoClimatico) else ev.accion
            carril = self._carril[clave]
            x0 = d2n(ev.inicio)
            x1 = d2n(ev.fin) if ev.fin else max(x_der, x0)
            vivos.add(ev.id)
            rect = self._rects.get(ev.id)
            if rect is None:
                rect = self._Rectangle((x0, carril - 0.35), x1 - x0, 0.7, facecolor=self.COLORES[clave],
                                       edgecolor="k", lw=0.6)
                self.ax_g.add_patch(rect)
                self._rects[ev.id] = rect
            rect.set_x(x0)
            rect.set_width(x1 - x0)
            rect.set_alpha(0.95 if self.sim.evento_vigente(ev, ahora) else 0.4)
            rect.set_hatch("//" if ev.fin is None else None)
        for eid in [k for k in self._rects if k not in vivos]:
            self._rects.pop(eid).remove()

    def _escribir_estado(self, m: Medicion) -> None:
        activos = ", ".join(m.eventos_activos) or "ninguno"
        t90_min = self.sim.invernadero.t90_s / 60.0
        lineas = [
            f"{m.instante:%d/%m/%Y  %H:%M}",
            f"Real {m.seg_reales:,.0f} s | x{m.velocidad:,.0f}" + ("  [PAUSA]" if m.pausado else ""),
            f"Ext  {m.temp_externa:5.1f} °C  {m.rad_externa:5.0f} W/m²",
            f"Int  {m.temp_interna:5.1f} °C  {m.rad_interna:5.0f} W/m²",
            f"t90 (interior->ext.): {t90_min:5.1f} min",
            f"Techo: {m.techo.value} (def: {self.sim.cfg.techo_por_defecto.value})",
            f"Cortinas: {m.cortinas.value} (def: {self.sim.cfg.cortinas_por_defecto.value})",
            f"Ventiladores: {'ON' if m.ventiladores else 'off'}",
            f"Activos: {activos}",
        ]
        import textwrap
        self._txt.set_text("\n".join(w for l in lineas for w in textwrap.wrap(l, 40) or [""]))
        self._btn_pausa.label.set_text("Reanudar" if m.pausado else "Pausar")

    def _sincronizar_controles(self) -> None:
        """Si la velocidad se cambió desde afuera (consola, otro hilo), refleja el cambio en el slider."""
        v = self._log_vel()
        if abs(v - self.slider.val) > 1e-3:
            self.slider.eventson = False
            self.slider.set_val(v)
            self.slider.eventson = True
            self._texto_slider(self.sim.velocidad)

    def mostrar(self) -> None:
        self._plt.show()


# =========================================================================== #
# 9. Demo
# =========================================================================== #
def _demo() -> None:
    t0 = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)
    sim = Simulador(inicio=t0, velocidad=900.0)      # 15 min simulados por segundo real

    # Sin eventos agendados: arranca con techo y cortinas cerrados y ventiladores apagados.
    # Los eventos se disparan con los botones del visualizador o por código, por ejemplo:
    #   sim.programar_clima(TipoClima.LLUVIA, t0 + timedelta(hours=3), t0 + timedelta(hours=6))
    #   sim.accion_ahora(AccionInterior.APERTURA_CORTINAS)

    with sim:
        Visualizador(sim, ventana_horas=48).mostrar()


if __name__ == "__main__":
    _demo()