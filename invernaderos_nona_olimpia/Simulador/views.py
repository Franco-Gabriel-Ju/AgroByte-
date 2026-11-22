import json
import threading
from datetime import datetime
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .invernadero import (
    Simulador,
    ConfigInvernadero,
    TipoClima,
    AccionInterior,
    EstadoTecho,
    EstadoCortinas,
    EventoInterior,
    EventoClimatico,
)

_simulator_instance: Simulador | None = None
_sim_lock = threading.Lock()


def get_simulator() -> Simulador:
    global _simulator_instance
    with _sim_lock:
        if _simulator_instance is None:
            # Iniciar a las 12:00:00 (mediodía) para radiación y luz diurna activa
            inicio = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
            cfg = ConfigInvernadero()
            # Por defecto: techo CERRADO (apagado), cortinas CERRADAS (apagado), ventiladores APAGADOS
            _simulator_instance = Simulador(
                cfg=cfg,
                inicio=inicio,
                velocidad=10.0,
                tick_real_s=0.1,
                intervalo_registro_s=5.0,
            )
            _simulator_instance.iniciar()
        return _simulator_instance


def reset_simulator(velocidad: float = 10.0) -> Simulador:
    global _simulator_instance
    with _sim_lock:
        if _simulator_instance is not None:
            try:
                _simulator_instance.detener()
            except Exception:
                pass
        inicio = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        cfg = ConfigInvernadero()
        _simulator_instance = Simulador(
            cfg=cfg,
            inicio=inicio,
            velocidad=velocidad,
            tick_real_s=0.1,
            intervalo_registro_s=5.0,
        )
        _simulator_instance.iniciar()
        return _simulator_instance


def simulador_index(request):
    """Vista principal para renderizar la interfaz web del simulador."""
    sim = get_simulator()
    med = sim.medicion_actual()
    context = {
        "temp_int": round(med.temp_interna, 1),
        "temp_ext": round(med.temp_externa, 1),
        "rad_int": round(med.rad_interna),
        "rad_ext": round(med.rad_externa),
        "techo": sim.invernadero.techo.value,
        "cortinas": sim.invernadero.cortinas.value,
        "ventiladores": sim.invernadero.ventiladores,
    }
    return render(request, "simulador.html", context)


def api_estado(request):
    """Retorna la telemetría actual y el estado completo del invernadero."""
    sim = get_simulator()
    with sim._lock:
        med = sim.medicion_actual()
        inv = sim.invernadero

        # Ciclo diurno y noche
        hora_dec = sim.ciclo.hora_decimal(med.instante)
        factor_noche = sim.ciclo.factor_noche(med.instante)
        es_noche = factor_noche > 0.45 or not (sim.cfg.hora_amanecer <= hora_dec <= sim.cfg.hora_atardecer)

        # Clima activo
        clima_actual = "NORMAL"
        for ev in sim.agenda.todos():
            if isinstance(ev, EventoClimatico) and ev.activo_en(med.instante):
                clima_actual = ev.tipo.name
                break

        # Mecanismos binarios (apagado / prendido)
        techo_prendido = (inv.techo == EstadoTecho.ABIERTO)
        cortinas_prendido = (inv.cortinas == EstadoCortinas.ABIERTAS)
        ventiladores_prendido = bool(inv.ventiladores)

        # Historial reciente para inicializar o alimentar los gráficos
        historial_raw = sim.historial.desde()
        recientes = historial_raw[-32:] if len(historial_raw) >= 32 else historial_raw
        historial = [
            {
                "hora": m.instante.strftime("%H:%M:%S"),
                "temp_int": round(m.temp_interna, 1),
                "temp_ext": round(m.temp_externa, 1),
                "rad_int": round(m.rad_interna),
                "rad_ext": round(m.rad_externa),
            }
            for m in recientes
        ]

        data = {
            "instante": med.instante.isoformat(),
            "hora": med.instante.strftime("%H:%M:%S"),
            "hora_decimal": round(hora_dec, 2),
            "es_noche": es_noche,
            "factor_noche": round(factor_noche, 2),
            "velocidad": round(sim.velocidad, 1),
            "pausado": sim.pausado,
            # Gráficos de temperatura y radiación
            "temp_interna": round(med.temp_interna, 1),
            "temp_externa": round(med.temp_externa, 1),
            "rad_interna": round(med.rad_interna),
            "rad_externa": round(med.rad_externa),
            # Estado de los mecanismos (apagado/prendido)
            "techo": inv.techo.value,
            "techo_prendido": techo_prendido,
            "cortinas": inv.cortinas.value,
            "cortinas_prendido": cortinas_prendido,
            "ventiladores": inv.ventiladores,
            "ventiladores_prendido": ventiladores_prendido,
            # Clima y modelo físico
            "clima": clima_actual,
            "factor_retardo": round(inv._factor_retardo_efectivo, 2),
            "tau_retardo_s": round(inv.tau_retardo_actual_s, 1),
            "t90_min": round(inv.t90_s / 60.0, 1),
            "historial": historial,
        }
    return JsonResponse(data)


@csrf_exempt
def api_actuador(request):
    """
    Controla los mecanismos del invernadero.
    Cada mecanismo solo tiene estado 'prendido' o 'apagado'.
    Por defecto todos los mecanismos están apagados.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    sim = get_simulator()
    try:
        payload = json.loads(request.body.decode("utf-8"))
        mecanismo = str(payload.get("mecanismo", "")).lower()
        estado = payload.get("estado")
    except Exception as e:
        return JsonResponse({"error": f"JSON inválido: {e}"}, status=400)

    prendido = (estado in [True, "prendido", "on", "1", 1])

    with sim._lock:
        if mecanismo == "techo":
            if prendido:
                sim.accion_ahora(AccionInterior.APERTURA_TECHO)
            else:
                sim.accion_ahora(AccionInterior.CIERRE_TECHO)
        elif mecanismo == "cortinas":
            if prendido:
                sim.accion_ahora(AccionInterior.APERTURA_CORTINAS)
            else:
                sim.accion_ahora(AccionInterior.CIERRE_CORTINAS)
        elif mecanismo == "ventiladores":
            if prendido:
                sim.accion_ahora(AccionInterior.VENTILADORES)
            else:
                # Cancelar eventos de ventiladores activos
                for ev in sim.agenda.todos():
                    if isinstance(ev, EventoInterior) and ev.accion == AccionInterior.VENTILADORES:
                        sim.cancelar_evento(ev.id)
                sim.invernadero.ventiladores = False
        else:
            return JsonResponse({"error": f"Mecanismo no reconocido: {mecanismo}"}, status=400)

        # Resolver el estado del invernadero de inmediato
        _, interiores = sim.agenda.snapshot()
        sim.invernadero._resolver_estados(sim.instante, interiores)

    return JsonResponse({
        "ok": True,
        "mecanismo": mecanismo,
        "estado": "prendido" if prendido else "apagado",
        "techo": sim.invernadero.techo.value,
        "techo_prendido": (sim.invernadero.techo == EstadoTecho.ABIERTO),
        "cortinas": sim.invernadero.cortinas.value,
        "cortinas_prendido": (sim.invernadero.cortinas == EstadoCortinas.ABIERTAS),
        "ventiladores": sim.invernadero.ventiladores,
        "ventiladores_prendido": bool(sim.invernadero.ventiladores),
    })


@csrf_exempt
def api_clima(request):
    """Establece el escenario climático de la simulación."""
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    sim = get_simulator()
    try:
        payload = json.loads(request.body.decode("utf-8"))
        clima_str = str(payload.get("clima", "NORMAL")).upper()
    except Exception as e:
        return JsonResponse({"error": f"JSON inválido: {e}"}, status=400)

    with sim._lock:
        # Cancelar eventos climáticos previos
        for ev in list(sim.agenda.todos()):
            if isinstance(ev, EventoClimatico):
                sim.cancelar_evento(ev.id)

        if clima_str != "NORMAL":
            try:
                tipo = TipoClima[clima_str]
                sim.clima_ahora(tipo)
            except KeyError:
                return JsonResponse({"error": f"TipoClima no reconocido: {clima_str}"}, status=400)

        climaticos, _ = sim.agenda.snapshot()
        sim._ext = sim.exterior.calcular(sim.instante, climaticos)

    return JsonResponse({"ok": True, "clima": clima_str})


@csrf_exempt
def api_velocidad(request):
    """Ajusta la velocidad del tiempo simulado o pausa/reanuda."""
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    sim = get_simulator()
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if "velocidad" in payload:
            sim.velocidad = max(0.1, min(float(payload["velocidad"]), 10000.0))
        if "pausado" in payload:
            if payload["pausado"]:
                sim.pausar()
            else:
                sim.reanudar()
    except Exception as e:
        return JsonResponse({"error": f"Error: {e}"}, status=400)

    return JsonResponse({
        "ok": True,
        "velocidad": sim.velocidad,
        "pausado": sim.pausado,
    })


@csrf_exempt
def api_reset(request):
    """Reinicia la simulación al estado inicial por defecto."""
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)
    reset_simulator()
    return JsonResponse({"ok": True, "mensaje": "Simulador reiniciado correctamente"})
