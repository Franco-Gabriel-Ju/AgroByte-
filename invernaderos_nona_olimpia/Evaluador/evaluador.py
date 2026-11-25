from __future__ import annotations

import threading
from datetime import datetime

from App.models import Alerta, Invernadero, Mecanismo, Parametro
from App.services import (
    asegurar_datos_iniciales,
    cambiar_mecanismo_por_tipo,
    registrar_alerta,
    resolver_alertas_activas,
)
from Simulador.invernadero import AccionInterior, EventoInterior


def sincronizar_mecanismo_en_simulador(sim, tipo: str, nuevo_estado: str) -> None:
    """Refleja un estado canónico de BD dentro del motor físico del Simulador."""
    if sim is None:
        return
    with sim._lock:
        if tipo == 'MEDIA_SOMBRA':
            accion = (
                AccionInterior.APERTURA_TECHO
                if nuevo_estado == 'DESPLEGADA'
                else AccionInterior.CIERRE_TECHO
            )
            sim.accion_ahora(accion)
        elif tipo == 'CORTINAS_LATERALES':
            accion = (
                AccionInterior.APERTURA_CORTINAS
                if nuevo_estado == 'ABIERTAS'
                else AccionInterior.CIERRE_CORTINAS
            )
            sim.accion_ahora(accion)
        elif tipo == 'VENTILACION':
            if nuevo_estado == 'ENCENDIDO':
                sim.accion_ahora(AccionInterior.VENTILADORES)
            else:
                for ev in list(sim.agenda.todos()):
                    if isinstance(ev, EventoInterior) and ev.accion == AccionInterior.VENTILADORES:
                        sim.cancelar_evento(ev.id)
                sim.invernadero.ventiladores = False
        _, interiores = sim.agenda.snapshot()
        sim.invernadero._resolver_estados(sim.instante, interiores)


class EvaluadorInvernadero:
    """
    Evalúa continuamente las lecturas del Simulador frente a los últimos parámetros
    configurados en la base de datos, genera alertas contextuales y ejecuta acciones
    automáticas (con retardo de persistencia o emergencia inmediata por viento).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.condiciones_activas: dict[str, bool] = {
            'temp_alta': False,
            'temp_baja': False,
            'rad_alta': False,
            'rad_baja': False,
            'viento_alto': False,
            'clima_severo': False,
        }
        self.recomendaciones_emitidas: dict[str, bool] = {
            'temp_alta': False,
            'temp_baja': False,
            'rad_alta': False,
            'viento_alto': False,
        }
        self._alertas_pendientes_bd: dict[str, bool] = {
            'TEMPERATURA': True,
            'RADIACION': True,
            'VIENTO': True,
            'CLIMA': True,
        }
        self.timer_desplegar_sombra: datetime | None = None
        self.timer_recoger_sombra: datetime | None = None
        self.timer_encender_vent: datetime | None = None
        self.timer_apagar_vent: datetime | None = None
        self._ultimo_estado_cache: dict = {}

    def reiniciar_estado(self) -> None:
        with self._lock:
            for clave in self.condiciones_activas:
                self.condiciones_activas[clave] = False
            for clave in self.recomendaciones_emitidas:
                self.recomendaciones_emitidas[clave] = False
            for clave in self._alertas_pendientes_bd:
                self._alertas_pendientes_bd[clave] = True
            self.timer_desplegar_sombra = None
            self.timer_recoger_sombra = None
            self.timer_encender_vent = None
            self.timer_apagar_vent = None
            self._ultimo_estado_cache = {}

    def _limpiar_timers(self) -> None:
        self.timer_desplegar_sombra = None
        self.timer_recoger_sombra = None
        self.timer_encender_vent = None
        self.timer_apagar_vent = None

    def _obtener_contexto_bd(self, instante: datetime, invernadero_id: int | None = None):
        inv = (
            Invernadero.objects.select_related('cultivo', 'cultivo__parametro').filter(id=invernadero_id).first()
            if invernadero_id is not None
            else Invernadero.objects.select_related('cultivo', 'cultivo__parametro').first()
        )
        if inv is None:
            inv = asegurar_datos_iniciales(instante)
            inv = Invernadero.objects.select_related('cultivo', 'cultivo__parametro').get(id=inv.id)

        param = getattr(inv.cultivo, 'parametro', None) if inv.cultivo else None
        if param is None:
            param = Parametro.objects.first()
        if param is None:
            inv = asegurar_datos_iniciales(instante)
            param = inv.cultivo.parametro

        mecanismos = {m.tipo: m.estado for m in Mecanismo.objects.filter(invernadero=inv)}
        return inv, param, mecanismos

    def _evaluar_alertas_umbrales(self, medicion, inv: Invernadero, param: Parametro) -> None:
        cultivo_nombre = inv.cultivo.nombre if inv.cultivo else 'cultivo activo'
        hora_str = medicion.instante.strftime('%H:%M:%S')
        es_manual = inv.modo == 'MANUAL'

        # 1. Temperatura alta
        if medicion.temp_interna > param.temp_max:
            if not self.condiciones_activas['temp_alta']:
                self.condiciones_activas['temp_alta'] = True
                self._alertas_pendientes_bd['TEMPERATURA'] = True
                nivel = 'CRITICO' if medicion.temp_interna >= param.temp_max + 3.0 else 'ADVERTENCIA'
                registrar_alerta(
                    id_invernadero=inv.id,
                    variable='TEMPERATURA',
                    valor=medicion.temp_interna,
                    umbral=param.temp_max,
                    nivel=nivel,
                    categoria='ALERTA',
                    titulo=f'Temperatura superior al umbral máximo ({medicion.temp_interna:.1f} °C)',
                    descripcion=(
                        f'[{hora_str}] La temperatura interna ({medicion.temp_interna:.1f} °C) superó el límite '
                        f'máximo de {param.temp_max:.1f} °C para {cultivo_nombre}, generando riesgo de estrés térmico.'
                    ),
                    fecha=medicion.instante,
                )
            if es_manual and not self.recomendaciones_emitidas['temp_alta']:
                self.recomendaciones_emitidas['temp_alta'] = True
                self._alertas_pendientes_bd['TEMPERATURA'] = True
                registrar_alerta(
                    id_invernadero=inv.id,
                    variable='TEMPERATURA',
                    valor=medicion.temp_interna,
                    umbral=param.temp_max,
                    nivel='INFO',
                    categoria='RECOMENDACION',
                    titulo='Sugerencia: reducir temperatura interior',
                    descripcion=(
                        f'[{hora_str}] Modo manual activo: se recomienda encender turbinas de ventilación '
                        f'o desplegar la media sombra.'
                    ),
                    fecha=medicion.instante,
                )
        elif medicion.temp_interna <= param.temp_max - 0.5:
            self.condiciones_activas['temp_alta'] = False
            self.recomendaciones_emitidas['temp_alta'] = False

        # 2. Temperatura baja
        if medicion.temp_interna < param.temp_min:
            if not self.condiciones_activas['temp_baja']:
                self.condiciones_activas['temp_baja'] = True
                self._alertas_pendientes_bd['TEMPERATURA'] = True
                nivel = 'CRITICO' if medicion.temp_interna <= param.temp_min - 3.0 else 'ADVERTENCIA'
                registrar_alerta(
                    id_invernadero=inv.id,
                    variable='TEMPERATURA',
                    valor=medicion.temp_interna,
                    umbral=param.temp_min,
                    nivel=nivel,
                    categoria='ALERTA',
                    titulo=f'Temperatura inferior al umbral mínimo ({medicion.temp_interna:.1f} °C)',
                    descripcion=(
                        f'[{hora_str}] La temperatura interna ({medicion.temp_interna:.1f} °C) descendió por debajo '
                        f'del mínimo configurado ({param.temp_min:.1f} °C) para {cultivo_nombre}.'
                    ),
                    fecha=medicion.instante,
                )
            if es_manual and not self.recomendaciones_emitidas['temp_baja']:
                self.recomendaciones_emitidas['temp_baja'] = True
                self._alertas_pendientes_bd['TEMPERATURA'] = True
                registrar_alerta(
                    id_invernadero=inv.id,
                    variable='TEMPERATURA',
                    valor=medicion.temp_interna,
                    umbral=param.temp_min,
                    nivel='INFO',
                    categoria='RECOMENDACION',
                    titulo='Sugerencia: conservar calor interior',
                    descripcion=(
                        f'[{hora_str}] Modo manual activo: se recomienda apagar ventilación y mantener '
                        f'cortinas cerradas.'
                    ),
                    fecha=medicion.instante,
                )
        elif medicion.temp_interna >= param.temp_min + 0.5:
            self.condiciones_activas['temp_baja'] = False
            self.recomendaciones_emitidas['temp_baja'] = False

        if not self.condiciones_activas['temp_alta'] and not self.condiciones_activas['temp_baja']:
            if self._alertas_pendientes_bd['TEMPERATURA']:
                resolver_alertas_activas(inv.id, variable='TEMPERATURA', fecha_resolucion=medicion.instante)
                self._alertas_pendientes_bd['TEMPERATURA'] = False

        # 3. Radiación alta
        if medicion.rad_interna > param.rad_max:
            if not self.condiciones_activas['rad_alta']:
                self.condiciones_activas['rad_alta'] = True
                self._alertas_pendientes_bd['RADIACION'] = True
                registrar_alerta(
                    id_invernadero=inv.id,
                    variable='RADIACION',
                    valor=medicion.rad_interna,
                    umbral=param.rad_max,
                    nivel='ADVERTENCIA',
                    categoria='ALERTA',
                    titulo=f'Radiación solar superior al umbral máximo ({medicion.rad_interna:.0f} W/m²)',
                    descripcion=(
                        f'[{hora_str}] La radiación interna ({medicion.rad_interna:.0f} W/m²) superó el umbral '
                        f'máximo de {param.rad_max:.0f} W/m² para {cultivo_nombre}, con riesgo de fotoinhibición.'
                    ),
                    fecha=medicion.instante,
                )
            if es_manual and not self.recomendaciones_emitidas['rad_alta']:
                self.recomendaciones_emitidas['rad_alta'] = True
                self._alertas_pendientes_bd['RADIACION'] = True
                registrar_alerta(
                    id_invernadero=inv.id,
                    variable='RADIACION',
                    valor=medicion.rad_interna,
                    umbral=param.rad_max,
                    nivel='INFO',
                    categoria='RECOMENDACION',
                    titulo='Sugerencia: desplegar media sombra',
                    descripcion=(
                        f'[{hora_str}] Modo manual activo: se recomienda desplegar la media sombra '
                        f'para disminuir la radiación incidente.'
                    ),
                    fecha=medicion.instante,
                )
        elif medicion.rad_interna <= param.rad_max * 0.96:
            self.condiciones_activas['rad_alta'] = False
            self.recomendaciones_emitidas['rad_alta'] = False

        # 4. Radiación baja (solo evaluada durante ventana diurna para evitar falsos positivos nocturnos)
        hora_dec = medicion.instante.hour + medicion.instante.minute / 60.0
        es_dia = 6.5 <= hora_dec < 19.5
        if es_dia and medicion.rad_interna < param.rad_min:
            if not self.condiciones_activas['rad_baja']:
                self.condiciones_activas['rad_baja'] = True
                self._alertas_pendientes_bd['RADIACION'] = True
                registrar_alerta(
                    id_invernadero=inv.id,
                    variable='RADIACION',
                    valor=medicion.rad_interna,
                    umbral=param.rad_min,
                    nivel='ADVERTENCIA',
                    categoria='ALERTA',
                    titulo=f'Radiación solar bajo el umbral mínimo ({medicion.rad_interna:.0f} W/m²)',
                    descripcion=(
                        f'[{hora_str}] La radiación interna ({medicion.rad_interna:.0f} W/m²) se encuentra por debajo '
                        f'del mínimo óptimo de {param.rad_min:.0f} W/m² debido a nubosidad o sombreado.'
                    ),
                    fecha=medicion.instante,
                )
        elif not es_dia or medicion.rad_interna >= param.rad_min * 1.05:
            self.condiciones_activas['rad_baja'] = False

        if not self.condiciones_activas['rad_alta'] and not self.condiciones_activas['rad_baja']:
            if self._alertas_pendientes_bd['RADIACION']:
                resolver_alertas_activas(inv.id, variable='RADIACION', fecha_resolucion=medicion.instante)
                self._alertas_pendientes_bd['RADIACION'] = False

        # 5. Viento crítico
        if medicion.viento_externo > param.viento_max:
            if not self.condiciones_activas['viento_alto']:
                self.condiciones_activas['viento_alto'] = True
                self._alertas_pendientes_bd['VIENTO'] = True
                registrar_alerta(
                    id_invernadero=inv.id,
                    variable='VIENTO',
                    valor=medicion.viento_externo,
                    umbral=param.viento_max,
                    nivel='CRITICO',
                    categoria='ALERTA',
                    titulo=f'Viento crítico sobre el umbral ({medicion.viento_externo:.1f} km/h)',
                    descripcion=(
                        f'[{hora_str}] La velocidad del viento ({medicion.viento_externo:.1f} km/h) superó el '
                        f'umbral máximo de seguridad ({param.viento_max:.1f} km/h). Riesgo estructural y de efecto vela.'
                    ),
                    fecha=medicion.instante,
                )
            if es_manual and not self.recomendaciones_emitidas['viento_alto']:
                self.recomendaciones_emitidas['viento_alto'] = True
                self._alertas_pendientes_bd['VIENTO'] = True
                registrar_alerta(
                    id_invernadero=inv.id,
                    variable='VIENTO',
                    valor=medicion.viento_externo,
                    umbral=param.viento_max,
                    nivel='CRITICO',
                    categoria='RECOMENDACION',
                    titulo='Sugerencia urgente: cerrar cortinas y recoger media sombra',
                    descripcion=(
                        f'[{hora_str}] Modo manual activo: cierre las cortinas laterales y recoja la media '
                        f'sombra de inmediato para proteger la estructura.'
                    ),
                    fecha=medicion.instante,
                )
        elif medicion.viento_externo <= param.viento_max * 0.95:
            self.condiciones_activas['viento_alto'] = False
            self.recomendaciones_emitidas['viento_alto'] = False

        if not self.condiciones_activas['viento_alto']:
            if self._alertas_pendientes_bd['VIENTO']:
                resolver_alertas_activas(inv.id, variable='VIENTO', fecha_resolucion=medicion.instante)
                self._alertas_pendientes_bd['VIENTO'] = False

        # 6. Clima severo
        severos = [ev for ev in medicion.eventos_activos if ev in ('Ventisca', 'Granizo', 'Tormenta eléctrica')]
        if severos:
            if not self.condiciones_activas['clima_severo']:
                self.condiciones_activas['clima_severo'] = True
                self._alertas_pendientes_bd['CLIMA'] = True
                nombre_clima = ', '.join(severos)
                registrar_alerta(
                    id_invernadero=inv.id,
                    variable='CLIMA',
                    valor=medicion.viento_externo,
                    umbral=param.viento_max,
                    nivel='CRITICO',
                    categoria='ALERTA',
                    titulo=f'Evento climático severo: {nombre_clima}',
                    descripcion=(
                        f'[{hora_str}] Condición severa detectada ({nombre_clima}). Viento actual '
                        f'{medicion.viento_externo:.1f} km/h y temp. ext. {medicion.temp_externa:.1f} °C.'
                    ),
                    fecha=medicion.instante,
                )
        else:
            self.condiciones_activas['clima_severo'] = False

        if not self.condiciones_activas['clima_severo']:
            if self._alertas_pendientes_bd['CLIMA']:
                resolver_alertas_activas(inv.id, variable='CLIMA', fecha_resolucion=medicion.instante)
                self._alertas_pendientes_bd['CLIMA'] = False

    def _aplicar_accion_automatica(
        self,
        inv: Invernadero,
        sim,
        tipo: str,
        nuevo_estado: str,
        variable_alerta: str,
        valor: float,
        umbral: float | None,
        nivel: str,
        titulo: str,
        descripcion: str,
        fecha: datetime,
    ) -> None:
        cambiar_mecanismo_por_tipo(
            id_invernadero=inv.id,
            tipo=tipo,
            nuevo_estado=nuevo_estado,
            origen='AUTOMATICO',
            fecha=fecha,
        )
        sincronizar_mecanismo_en_simulador(sim, tipo, nuevo_estado)
        registrar_alerta(
            id_invernadero=inv.id,
            variable=variable_alerta,
            valor=valor,
            umbral=umbral,
            nivel=nivel,
            categoria='ACTIVACION',
            titulo=titulo,
            descripcion=descripcion,
            fecha=fecha,
        )

    def _ejecutar_automatizacion(
        self,
        medicion,
        sim,
        inv: Invernadero,
        param: Parametro,
        mecanismos: dict[str, str],
    ) -> None:
        ahora = medicion.instante
        hora_str = ahora.strftime('%H:%M:%S')
        persistencia_s = max(1, int(param.tiempo_persistencia_min)) * 60.0
        viento_seguro = medicion.viento_externo <= param.viento_max

        # ------------------------------------------------------------------
        # A. CORTINAS LATERALES: cierre inmediato si viento > umbral; apertura si <= umbral
        # ------------------------------------------------------------------
        estado_cortinas = mecanismos.get('CORTINAS_LATERALES', 'CERRADAS')
        if not viento_seguro:
            if estado_cortinas != 'CERRADAS':
                self._aplicar_accion_automatica(
                    inv=inv,
                    sim=sim,
                    tipo='CORTINAS_LATERALES',
                    nuevo_estado='CERRADAS',
                    variable_alerta='CORTINAS_LATERALES',
                    valor=medicion.viento_externo,
                    umbral=param.viento_max,
                    nivel='CRITICO',
                    titulo='Cierre automático de cortinas laterales por viento',
                    descripcion=(
                        f'[{hora_str}] Activación automática: cortinas laterales CERRADAS porque el viento '
                        f'({medicion.viento_externo:.1f} km/h) superó el umbral de {param.viento_max:.1f} km/h.'
                    ),
                    fecha=ahora,
                )
        else:
            if estado_cortinas != 'ABIERTAS':
                self._aplicar_accion_automatica(
                    inv=inv,
                    sim=sim,
                    tipo='CORTINAS_LATERALES',
                    nuevo_estado='ABIERTAS',
                    variable_alerta='CORTINAS_LATERALES',
                    valor=medicion.viento_externo,
                    umbral=param.viento_max,
                    nivel='INFO',
                    titulo='Apertura automática de cortinas laterales',
                    descripcion=(
                        f'[{hora_str}] Activación automática: cortinas laterales ABIERTAS porque el viento '
                        f'({medicion.viento_externo:.1f} km/h) se encuentra bajo el umbral de {param.viento_max:.1f} km/h.'
                    ),
                    fecha=ahora,
                )

        # ------------------------------------------------------------------
        # B. MEDIA SOMBRA: emergencia inmediata por viento + persistencia agronómica
        # ------------------------------------------------------------------
        estado_sombra = mecanismos.get('MEDIA_SOMBRA', 'RECOGIDA')
        if not viento_seguro:
            self.timer_desplegar_sombra = None
            self.timer_recoger_sombra = None
            if estado_sombra == 'DESPLEGADA':
                self._aplicar_accion_automatica(
                    inv=inv,
                    sim=sim,
                    tipo='MEDIA_SOMBRA',
                    nuevo_estado='RECOGIDA',
                    variable_alerta='MEDIA_SOMBRA',
                    valor=medicion.viento_externo,
                    umbral=param.viento_max,
                    nivel='CRITICO',
                    titulo='Recogido automático de emergencia de media sombra',
                    descripcion=(
                        f'[{hora_str}] Activación automática de emergencia (inmediata): media sombra RECOGIDA por '
                        f'viento crítico ({medicion.viento_externo:.1f} km/h > {param.viento_max:.1f} km/h) '
                        f'para evitar efecto vela y proteger la estructura.'
                    ),
                    fecha=ahora,
                )
        elif medicion.rad_interna > param.rad_max or medicion.temp_interna > param.temp_max:
            self.timer_recoger_sombra = None
            if estado_sombra != 'DESPLEGADA':
                if self.timer_desplegar_sombra is None:
                    self.timer_desplegar_sombra = ahora
                elif (ahora - self.timer_desplegar_sombra).total_seconds() >= persistencia_s:
                    supero_rad = medicion.rad_interna > param.rad_max
                    motivo_val = medicion.rad_interna if supero_rad else medicion.temp_interna
                    motivo_umb = param.rad_max if supero_rad else param.temp_max
                    motivo_txt = (
                        f'radiación interna ({medicion.rad_interna:.0f} > {param.rad_max:.0f} W/m²)'
                        if supero_rad
                        else f'temperatura interna ({medicion.temp_interna:.1f} > {param.temp_max:.1f} °C)'
                    )
                    self._aplicar_accion_automatica(
                        inv=inv,
                        sim=sim,
                        tipo='MEDIA_SOMBRA',
                        nuevo_estado='DESPLEGADA',
                        variable_alerta='MEDIA_SOMBRA',
                        valor=motivo_val,
                        umbral=motivo_umb,
                        nivel='ADVERTENCIA',
                        titulo='Despliegue automático de media sombra',
                        descripcion=(
                            f'[{hora_str}] Activación automática tras {param.tiempo_persistencia_min} min de '
                            f'persistencia continua: media sombra DESPLEGADA por {motivo_txt} con viento seguro.'
                        ),
                        fecha=ahora,
                    )
                    self.timer_desplegar_sombra = None
            else:
                self.timer_desplegar_sombra = None
        elif medicion.rad_interna < param.rad_min and medicion.temp_interna <= param.temp_max:
            self.timer_desplegar_sombra = None
            if estado_sombra == 'DESPLEGADA':
                if self.timer_recoger_sombra is None:
                    self.timer_recoger_sombra = ahora
                elif (ahora - self.timer_recoger_sombra).total_seconds() >= persistencia_s:
                    self._aplicar_accion_automatica(
                        inv=inv,
                        sim=sim,
                        tipo='MEDIA_SOMBRA',
                        nuevo_estado='RECOGIDA',
                        variable_alerta='MEDIA_SOMBRA',
                        valor=medicion.rad_interna,
                        umbral=param.rad_min,
                        nivel='INFO',
                        titulo='Recogido automático de media sombra',
                        descripcion=(
                            f'[{hora_str}] Activación automática tras {param.tiempo_persistencia_min} min de '
                            f'persistencia continua: media sombra RECOGIDA por radiación baja '
                            f'({medicion.rad_interna:.0f} < {param.rad_min:.0f} W/m²) con temperatura '
                            f'dentro de rango ({medicion.temp_interna:.1f} <= {param.temp_max:.1f} °C).'
                        ),
                        fecha=ahora,
                    )
                    self.timer_recoger_sombra = None
            else:
                self.timer_recoger_sombra = None
        else:
            # Fluctuación pasajera o banda operativa normal: cancelar timers pendientes
            self.timer_desplegar_sombra = None
            self.timer_recoger_sombra = None

        # ------------------------------------------------------------------
        # C. VENTILACIÓN / TURBINAS: con retardo de persistencia por temperatura
        # ------------------------------------------------------------------
        estado_vent = mecanismos.get('VENTILACION', 'APAGADO')
        temp_media = (param.temp_min + param.temp_max) / 2.0
        if medicion.temp_interna > param.temp_max:
            self.timer_apagar_vent = None
            if estado_vent != 'ENCENDIDO':
                if self.timer_encender_vent is None:
                    self.timer_encender_vent = ahora
                elif (ahora - self.timer_encender_vent).total_seconds() >= persistencia_s:
                    self._aplicar_accion_automatica(
                        inv=inv,
                        sim=sim,
                        tipo='VENTILACION',
                        nuevo_estado='ENCENDIDO',
                        variable_alerta='VENTILACION',
                        valor=medicion.temp_interna,
                        umbral=param.temp_max,
                        nivel='ADVERTENCIA',
                        titulo='Encendido automático de ventilación',
                        descripcion=(
                            f'[{hora_str}] Activación automática tras {param.tiempo_persistencia_min} min de '
                            f'persistencia: turbinas ENCENDIDAS por temperatura interna '
                            f'({medicion.temp_interna:.1f} °C > {param.temp_max:.1f} °C).'
                        ),
                        fecha=ahora,
                    )
                    self.timer_encender_vent = None
            else:
                self.timer_encender_vent = None
        elif medicion.temp_interna <= temp_media:
            self.timer_encender_vent = None
            if estado_vent == 'ENCENDIDO':
                if self.timer_apagar_vent is None:
                    self.timer_apagar_vent = ahora
                elif (ahora - self.timer_apagar_vent).total_seconds() >= persistencia_s:
                    self._aplicar_accion_automatica(
                        inv=inv,
                        sim=sim,
                        tipo='VENTILACION',
                        nuevo_estado='APAGADO',
                        variable_alerta='VENTILACION',
                        valor=medicion.temp_interna,
                        umbral=temp_media,
                        nivel='INFO',
                        titulo='Apagado automático de ventilación',
                        descripcion=(
                            f'[{hora_str}] Activación automática tras {param.tiempo_persistencia_min} min: '
                            f'turbinas APAGADAS al estabilizarse la temperatura ({medicion.temp_interna:.1f} °C).'
                        ),
                        fecha=ahora,
                    )
                    self.timer_apagar_vent = None
            else:
                self.timer_apagar_vent = None
        else:
            self.timer_encender_vent = None
            self.timer_apagar_vent = None

    def _actualizar_cache_estado(self, inv: Invernadero, param: Parametro, ahora: datetime) -> None:
        persistencia_s = max(1, int(param.tiempo_persistencia_min)) * 60.0

        def _info_timer(inicio: datetime | None) -> dict:
            if inicio is None:
                return {'activo': False, 'transcurrido_s': 0, 'restante_s': int(persistencia_s)}
            trans = max(0.0, (ahora - inicio).total_seconds())
            return {
                'activo': True,
                'inicio': inicio.strftime('%H:%M:%S'),
                'transcurrido_s': int(round(trans)),
                'restante_s': int(max(0, round(persistencia_s - trans))),
            }

        self._ultimo_estado_cache = {
            'modo': inv.modo,
            'cultivo': inv.cultivo.nombre if inv.cultivo else 'Sin cultivo',
            'parametros': {
                'temp_min': param.temp_min,
                'temp_max': param.temp_max,
                'rad_min': param.rad_min,
                'rad_max': param.rad_max,
                'viento_max': param.viento_max,
                'tiempo_persistencia_min': param.tiempo_persistencia_min,
            },
            'persistencia_requerida_s': int(persistencia_s),
            'timers': {
                'desplegar_media_sombra': _info_timer(self.timer_desplegar_sombra),
                'recoger_media_sombra': _info_timer(self.timer_recoger_sombra),
                'encender_ventilacion': _info_timer(self.timer_encender_vent),
                'apagar_ventilacion': _info_timer(self.timer_apagar_vent),
            },
            'condiciones_activas': dict(self.condiciones_activas),
        }

    def evaluar(self, medicion, sim=None, invernadero_id: int | None = None) -> dict:
        with self._lock:
            inv, param, mecanismos = self._obtener_contexto_bd(medicion.instante, invernadero_id)
            self._evaluar_alertas_umbrales(medicion, inv, param)
            if inv.modo == 'AUTOMATICO':
                self._ejecutar_automatizacion(medicion, sim, inv, param, mecanismos)
            else:
                self._limpiar_timers()
            self._actualizar_cache_estado(inv, param, medicion.instante)
            return dict(self._ultimo_estado_cache)

    def estado_resumen(self, instante_actual: datetime | None = None) -> dict:
        with self._lock:
            inv, param, _ = self._obtener_contexto_bd(instante_actual or datetime.now())
            self._actualizar_cache_estado(inv, param, instante_actual or datetime.now())
            return dict(self._ultimo_estado_cache)


_evaluador_instance: EvaluadorInvernadero | None = None
_eval_lock = threading.Lock()


def obtener_evaluador() -> EvaluadorInvernadero:
    global _evaluador_instance
    with _eval_lock:
        if _evaluador_instance is None:
            _evaluador_instance = EvaluadorInvernadero()
        return _evaluador_instance


def resetear_evaluador() -> EvaluadorInvernadero:
    ev = obtener_evaluador()
    ev.reiniciar_estado()
    return ev
