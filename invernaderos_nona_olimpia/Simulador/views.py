import json
import threading
from datetime import datetime

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from App.models import (
    Alerta,
    HistorialClima,
    HistorialRadiacion,
    HistorialTemperatura,
    HistorialViento,
    Invernadero,
    Mecanismo,
    Parametro,
)
from App.services import (
    actualizar_pronostico_extendido,
    asegurar_datos_iniciales,
    cambiar_mecanismo_por_tipo,
    cambiar_modo_invernadero,
    registrar_alerta,
    registrar_clima,
    registrar_lectura_sensores,
)
from Evaluador.evaluador import (
    obtener_evaluador,
    resetear_evaluador,
    sincronizar_mecanismo_en_simulador,
)

from .invernadero import (
    ConfigInvernadero,
    EstadoCortinas,
    EstadoTecho,
    EventoClimatico,
    Simulador,
    TipoClima,
)

_simulator_instance: Simulador | None = None
_sim_lock = threading.Lock()
_ultimo_clima_registrado: tuple[str, datetime] | None = None


def _clima_actual_sim(sim: Simulador, instante: datetime) -> str:
    clima_actual = 'NORMAL'
    for ev in sim.agenda.todos():
        if isinstance(ev, EventoClimatico) and ev.activo_en(instante):
            clima_actual = ev.tipo.name
            break
    return clima_actual


def _on_medicion_simulada(med) -> None:
    """Callback ejecutado fuera de sim._lock por cada punto registrado del Simulador."""
    global _ultimo_clima_registrado, _simulator_instance
    inv = Invernadero.objects.first()
    if inv is None:
        inv = asegurar_datos_iniciales(med.instante)

    registrar_lectura_sensores(
        id_invernadero=inv.id,
        grados=med.temp_interna,
        radiacion=med.rad_interna,
        viento=med.viento_externo,
        temp_externa=med.temp_externa,
        rad_externa=med.rad_externa,
        fecha=med.instante,
    )

    sim = _simulator_instance
    clima_actual = _clima_actual_sim(sim, med.instante) if sim else 'NORMAL'
    debe_registrar_clima = (
        _ultimo_clima_registrado is None
        or _ultimo_clima_registrado[0] != clima_actual
        or (med.instante - _ultimo_clima_registrado[1]).total_seconds() >= 3600
    )
    if debe_registrar_clima:
        prob = sim._ext.prob_lluvia if sim else 5
        registrar_clima(
            id_invernadero=inv.id,
            estado=clima_actual,
            temp_externa=med.temp_externa,
            viento_estimado=med.viento_externo,
            prob_lluvia=prob,
            es_pronostico=False,
            fecha=med.instante,
        )
        actualizar_pronostico_extendido(
            id_invernadero=inv.id,
            fecha_base=med.instante,
            clima_actual=clima_actual,
            temp_base=med.temp_externa,
            viento_base=med.viento_externo,
        )
        _ultimo_clima_registrado = (clima_actual, med.instante)

    obtener_evaluador().evaluar(med, sim=sim, invernadero_id=inv.id)


def _sincronizar_simulador_desde_bd(sim: Simulador, inv: Invernadero) -> None:
    mecanismos = Mecanismo.objects.filter(invernadero=inv)
    for mec in mecanismos:
        sincronizar_mecanismo_en_simulador(sim, mec.tipo, mec.estado)


def get_simulator() -> Simulador:
    global _simulator_instance, _ultimo_clima_registrado
    with _sim_lock:
        if _simulator_instance is None:
            sin_datos_previos = not HistorialTemperatura.objects.exists()
            hora_inicio = 11 if sin_datos_previos else 12
            inicio = datetime.now().replace(hour=hora_inicio, minute=0, second=0, microsecond=0)

            inv = asegurar_datos_iniciales(inicio)
            if not sin_datos_previos:
                ultima_temp = HistorialTemperatura.objects.order_by('-fecha').first()
                if ultima_temp and ultima_temp.fecha > inicio:
                    inicio = ultima_temp.fecha

            cfg = ConfigInvernadero()
            sim = Simulador(
                cfg=cfg,
                inicio=inicio,
                velocidad=30.0,
                tick_real_s=0.2,
                intervalo_registro_s=30.0,
            )
            _sincronizar_simulador_desde_bd(sim, inv)
            _ultimo_clima_registrado = None
            _simulator_instance = sim
            sim.registrar_callback(_on_medicion_simulada)

            if sin_datos_previos:
                # Poblar 1 hora simulada real inicial pasando por la física y el Evaluador
                sim.avanzar(3600.0)
            else:
                med = sim.medicion_actual()
                actualizar_pronostico_extendido(
                    id_invernadero=inv.id,
                    fecha_base=med.instante,
                    clima_actual='NORMAL',
                    temp_base=med.temp_externa,
                    viento_base=med.viento_externo,
                )

            sim.iniciar()
        return _simulator_instance


def reset_simulator(velocidad: float = 30.0) -> Simulador:
    global _simulator_instance, _ultimo_clima_registrado
    with _sim_lock:
        if _simulator_instance is not None:
            try:
                _simulator_instance.detener()
            except Exception:
                pass
        inicio = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        inv = asegurar_datos_iniciales(inicio)
        resetear_evaluador()
        _ultimo_clima_registrado = None

        cfg = ConfigInvernadero()
        sim = Simulador(
            cfg=cfg,
            inicio=inicio,
            velocidad=velocidad,
            tick_real_s=0.2,
            intervalo_registro_s=30.0,
        )
        _sincronizar_simulador_desde_bd(sim, inv)
        _simulator_instance = sim
        sim.registrar_callback(_on_medicion_simulada)
        _on_medicion_simulada(sim.medicion_actual())
        sim.iniciar()
        return sim


def obtener_instante_actual() -> datetime:
    """Referencia temporal única compartida por Simulador, Evaluador y App."""
    return get_simulator().instante


def detener_simulator() -> None:
    """Detiene y limpia la instancia singleton del simulador (útil en tests y apagado)."""
    global _simulator_instance, _ultimo_clima_registrado
    with _sim_lock:
        if _simulator_instance is not None:
            try:
                _simulator_instance.detener()
            except Exception:
                pass
            _simulator_instance = None
        _ultimo_clima_registrado = None


def simulador_index(request):
    """Vista principal para renderizar la interfaz web del simulador."""
    sim = get_simulator()
    med = sim.medicion_actual()
    context = {
        'temp_int': round(med.temp_interna, 1),
        'temp_ext': round(med.temp_externa, 1),
        'rad_int': round(med.rad_interna),
        'rad_ext': round(med.rad_externa),
        'viento_ext': round(med.viento_externo, 1),
        'techo': sim.invernadero.techo.value,
        'cortinas': sim.invernadero.cortinas.value,
        'ventiladores': sim.invernadero.ventiladores,
    }
    return render(request, 'simulador.html', context)


def api_estado(request):
    """Retorna telemetría actual, parámetros configurados, timers del Evaluador y alertas reales."""
    sim = get_simulator()
    with sim._lock:
        med = sim.medicion_actual()
        inv_fis = sim.invernadero

        hora_dec = sim.ciclo.hora_decimal(med.instante)
        factor_noche = sim.ciclo.factor_noche(med.instante)
        es_noche = factor_noche > 0.45 or not (sim.cfg.hora_amanecer <= hora_dec <= sim.cfg.hora_atardecer)
        clima_actual = _clima_actual_sim(sim, med.instante)

        techo_prendido = inv_fis.techo == EstadoTecho.ABIERTO
        cortinas_prendido = inv_fis.cortinas == EstadoCortinas.ABIERTAS
        ventiladores_prendido = bool(inv_fis.ventiladores)

        historial_raw = sim.historial.desde()
        recientes = historial_raw[-40:] if len(historial_raw) >= 40 else historial_raw
        historial = [
            {
                'hora': m.instante.strftime('%H:%M:%S'),
                'temp_int': round(m.temp_interna, 1),
                'temp_ext': round(m.temp_externa, 1),
                'rad_int': round(m.rad_interna),
                'rad_ext': round(m.rad_externa),
                'viento': round(m.viento_externo, 1),
            }
            for m in recientes
        ]

        data = {
            'instante': med.instante.isoformat(),
            'fecha': med.instante.strftime('%Y-%m-%d'),
            'hora': med.instante.strftime('%H:%M:%S'),
            'hora_decimal': round(hora_dec, 2),
            'es_noche': es_noche,
            'factor_noche': round(factor_noche, 2),
            'velocidad': round(sim.velocidad, 1),
            'pausado': sim.pausado,
            'temp_interna': round(med.temp_interna, 1),
            'temp_externa': round(med.temp_externa, 1),
            'rad_interna': round(med.rad_interna),
            'rad_externa': round(med.rad_externa),
            'viento_externo': round(med.viento_externo, 1),
            'viento_manual': sim.viento_manual,
            'techo': inv_fis.techo.value,
            'techo_prendido': techo_prendido,
            'cortinas': inv_fis.cortinas.value,
            'cortinas_prendido': cortinas_prendido,
            'ventiladores': inv_fis.ventiladores,
            'ventiladores_prendido': ventiladores_prendido,
            'clima': clima_actual,
            'factor_retardo': round(inv_fis._factor_retardo_efectivo, 2),
            'tau_retardo_s': round(inv_fis.tau_retardo_actual_s, 1),
            't90_min': round(inv_fis.t90_s / 60.0, 1),
            'historial': historial,
        }

    # Lecturas ORM fuera de sim._lock
    inv_db = Invernadero.objects.select_related('cultivo', 'cultivo__parametro').first()
    eval_estado = obtener_evaluador().estado_resumen(med.instante)
    alertas_qs = Alerta.objects.filter(invernadero=inv_db).order_by('-fecha')[:10] if inv_db else []

    data['modo'] = inv_db.modo if inv_db else 'AUTOMATICO'
    data['cultivo'] = inv_db.cultivo.nombre if inv_db and inv_db.cultivo else 'Lechuga Morada'
    data['parametros'] = eval_estado['parametros']
    data['evaluador'] = {
        'timers': eval_estado['timers'],
        'persistencia_requerida_s': eval_estado['persistencia_requerida_s'],
    }
    data['alertas'] = [
        {
            'id': a.id,
            'hora': a.fecha.strftime('%H:%M:%S'),
            'clima': data['clima'],
            'categoria': a.categoria,
            'nivel': a.nivel,
            'tipo': a.titulo or a.variable,
            'detalle': a.descripcion,
            'es_critico': a.nivel == 'CRITICO',
        }
        for a in alertas_qs
    ]
    return JsonResponse(data)


@csrf_exempt
def api_actuador(request):
    """Controla manualmente los mecanismos desde el Simulador y persiste en BD."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    sim = get_simulator()
    try:
        payload = json.loads(request.body.decode('utf-8'))
        mecanismo = str(payload.get('mecanismo', '')).lower()
        estado = payload.get('estado')
    except Exception as e:
        return JsonResponse({'error': f'JSON inválido: {e}'}, status=400)

    prendido = estado in [True, 'prendido', 'on', '1', 1, 'desplegada', 'abiertas', 'encendido']

    mapa = {
        'techo': ('MEDIA_SOMBRA', 'DESPLEGADA' if prendido else 'RECOGIDA'),
        'media_sombra': ('MEDIA_SOMBRA', 'DESPLEGADA' if prendido else 'RECOGIDA'),
        'cortinas': ('CORTINAS_LATERALES', 'ABIERTAS' if prendido else 'CERRADAS'),
        'cortinas_laterales': ('CORTINAS_LATERALES', 'ABIERTAS' if prendido else 'CERRADAS'),
        'ventiladores': ('VENTILACION', 'ENCENDIDO' if prendido else 'APAGADO'),
        'ventilacion': ('VENTILACION', 'ENCENDIDO' if prendido else 'APAGADO'),
    }
    if mecanismo not in mapa:
        return JsonResponse({'error': f'Mecanismo no reconocido: {mecanismo}'}, status=400)

    tipo_bd, estado_bd = mapa[mecanismo]
    instante = sim.instante
    sincronizar_mecanismo_en_simulador(sim, tipo_bd, estado_bd)

    inv = Invernadero.objects.first() or asegurar_datos_iniciales(instante)
    if inv.modo == 'AUTOMATICO':
        cambiar_modo_invernadero(inv.id, 'MANUAL', fecha=instante)
        registrar_alerta(
            id_invernadero=inv.id,
            variable='MODO',
            valor=0.0,
            nivel='INFO',
            categoria='ACTIVACION',
            titulo='Cambio a modo Manual desde Simulador',
            descripcion=f'[{instante:%H:%M:%S}] Al operar un mecanismo manualmente, el sistema pasó a modo MANUAL.',
            fecha=instante,
        )

    cambiar_mecanismo_por_tipo(
        id_invernadero=inv.id,
        tipo=tipo_bd,
        nuevo_estado=estado_bd,
        origen='SIMULADOR',
        fecha=instante,
    )
    registrar_alerta(
        id_invernadero=inv.id,
        variable=tipo_bd,
        valor=1.0 if prendido else 0.0,
        nivel='INFO',
        categoria='ACTIVACION',
        titulo=f'Activación manual (Simulador): {tipo_bd.replace("_", " ").title()} -> {estado_bd}',
        descripcion=(
            f'[{instante:%H:%M:%S}] Activación manual desde el Simulador: '
            f'{tipo_bd.replace("_", " ").lower()} pasó a estado {estado_bd}.'
        ),
        fecha=instante,
    )

    return JsonResponse({
        'ok': True,
        'mecanismo': mecanismo,
        'tipo_bd': tipo_bd,
        'estado_bd': estado_bd,
        'estado': 'prendido' if prendido else 'apagado',
        'techo': sim.invernadero.techo.value,
        'techo_prendido': sim.invernadero.techo == EstadoTecho.ABIERTO,
        'cortinas': sim.invernadero.cortinas.value,
        'cortinas_prendido': sim.invernadero.cortinas == EstadoCortinas.ABIERTAS,
        'ventiladores': sim.invernadero.ventiladores,
        'ventiladores_prendido': bool(sim.invernadero.ventiladores),
    })


@csrf_exempt
def api_clima(request):
    """Establece el escenario climático de la simulación (incluye Ventisca y Granizo)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    sim = get_simulator()
    try:
        payload = json.loads(request.body.decode('utf-8'))
        clima_str = str(payload.get('clima', 'NORMAL')).upper()
    except Exception as e:
        return JsonResponse({'error': f'JSON inválido: {e}'}, status=400)

    with sim._lock:
        for ev in list(sim.agenda.todos()):
            if isinstance(ev, EventoClimatico):
                sim.cancelar_evento(ev.id)

        if clima_str != 'NORMAL':
            try:
                tipo = TipoClima[clima_str]
                if tipo == TipoClima.VENTISCA:
                    # Permitir que la rampa progresiva de Ventisca eleve el viento automáticamente
                    sim._viento_manual = None
                sim.clima_ahora(tipo)
            except KeyError:
                return JsonResponse({'error': f'TipoClima no reconocido: {clima_str}'}, status=400)

        climaticos, _ = sim.agenda.snapshot()
        sim._ext = sim.exterior.calcular(sim.instante, climaticos, sim._viento_manual)
        med = sim.medicion_actual()
        prob = sim._ext.prob_lluvia

    inv = Invernadero.objects.first() or asegurar_datos_iniciales(med.instante)
    registrar_clima(
        id_invernadero=inv.id,
        estado=clima_str,
        temp_externa=med.temp_externa,
        viento_estimado=med.viento_externo,
        prob_lluvia=prob,
        es_pronostico=False,
        fecha=med.instante,
    )
    actualizar_pronostico_extendido(
        id_invernadero=inv.id,
        fecha_base=med.instante,
        clima_actual=clima_str,
        temp_base=med.temp_externa,
        viento_base=med.viento_externo,
    )
    obtener_evaluador().evaluar(med, sim=sim, invernadero_id=inv.id)
    return JsonResponse({'ok': True, 'clima': clima_str, 'viento_externo': round(med.viento_externo, 1)})


@csrf_exempt
def api_viento(request):
    """Permite fijar manualmente la velocidad del viento exterior o devolverlo a modo clima automático."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    sim = get_simulator()
    try:
        payload = json.loads(request.body.decode('utf-8'))
        viento = payload.get('viento')
    except Exception as e:
        return JsonResponse({'error': f'JSON inválido: {e}'}, status=400)

    if viento is None or viento == '':
        sim.viento_manual = None
    else:
        sim.viento_manual = max(0.0, min(float(viento), 150.0))

    med = sim.medicion_actual()
    inv = Invernadero.objects.first() or asegurar_datos_iniciales(med.instante)
    registrar_lectura_sensores(
        id_invernadero=inv.id,
        grados=med.temp_interna,
        radiacion=med.rad_interna,
        viento=med.viento_externo,
        temp_externa=med.temp_externa,
        rad_externa=med.rad_externa,
        fecha=med.instante,
    )
    obtener_evaluador().evaluar(med, sim=sim, invernadero_id=inv.id)
    return JsonResponse({
        'ok': True,
        'viento_manual': sim.viento_manual,
        'viento_externo': round(med.viento_externo, 1),
    })


@csrf_exempt
def api_modo(request):
    """Cambia el modo de operación (AUTOMATICO / MANUAL) sincronizado con BD y Evaluador."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    sim = get_simulator()
    try:
        payload = json.loads(request.body.decode('utf-8'))
        modo = str(payload.get('modo', 'AUTOMATICO')).upper()
    except Exception as e:
        return JsonResponse({'error': f'JSON inválido: {e}'}, status=400)

    if modo not in ('AUTOMATICO', 'MANUAL'):
        return JsonResponse({'error': 'Modo inválido'}, status=400)

    instante = sim.instante
    inv = Invernadero.objects.first() or asegurar_datos_iniciales(instante)
    cambiar_modo_invernadero(inv.id, modo, fecha=instante)
    registrar_alerta(
        id_invernadero=inv.id,
        variable='MODO',
        valor=1.0 if modo == 'AUTOMATICO' else 0.0,
        nivel='INFO',
        categoria='ACTIVACION',
        titulo=f'Modo {modo.title()} activado',
        descripcion=f'[{instante:%H:%M:%S}] Se estableció el modo de operación en {modo}.',
        fecha=instante,
    )
    if modo == 'AUTOMATICO':
        obtener_evaluador().evaluar(sim.medicion_actual(), sim=sim, invernadero_id=inv.id)

    return JsonResponse({'ok': True, 'modo': modo})


@csrf_exempt
def api_velocidad(request):
    """Ajusta la velocidad del tiempo simulado, pausa/reanuda o adelanta minutos simulados."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    sim = get_simulator()
    try:
        payload = json.loads(request.body.decode('utf-8'))
        if 'velocidad' in payload:
            sim.velocidad = max(0.1, min(float(payload['velocidad']), 10000.0))
        if 'pausado' in payload:
            if payload['pausado']:
                sim.pausar()
            else:
                sim.reanudar()
        if 'adelantar_min' in payload and float(payload['adelantar_min']) > 0:
            sim.avanzar(float(payload['adelantar_min']) * 60.0)
    except Exception as e:
        return JsonResponse({'error': f'Error: {e}'}, status=400)

    return JsonResponse({
        'ok': True,
        'velocidad': sim.velocidad,
        'pausado': sim.pausado,
        'hora': sim.instante.strftime('%H:%M:%S'),
    })


@csrf_exempt
def api_reset(request):
    """Reinicia la simulación al estado inicial por defecto."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    reset_simulator()
    return JsonResponse({'ok': True, 'mensaje': 'Simulador reiniciado correctamente'})
