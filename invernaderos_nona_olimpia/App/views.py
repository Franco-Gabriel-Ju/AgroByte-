import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from Evaluador.evaluador import obtener_evaluador, sincronizar_mecanismo_en_simulador
from Simulador.views import get_simulator, obtener_instante_actual

from .models import (
    Alerta,
    Cultivo,
    HistorialClima,
    HistorialMecanismo,
    HistorialRadiacion,
    HistorialTemperatura,
    HistorialViento,
    Invernadero,
    Mecanismo,
    Parametro,
    Reporte,
    Usuario,
)
from .services import (
    ETIQUETAS_CLIMA,
    asegurar_datos_iniciales,
    cambiar_mecanismo_por_tipo,
    cambiar_modo_invernadero,
    eliminar_reporte,
    establecer_parametros_cultivo,
    generar_reporte_csv,
    marcar_alertas_leidas,
    registrar_alerta,
    registrar_cultivo,
    registrar_usuario,
    seleccionar_cultivo_invernadero,
    validar_usuario,
)

DIAS_ES = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom']
MESES_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

TIPO_ALERTA_FRONT = {
    'ALERTA': ('alert', 'Alerta'),
    'RECOMENDACION': ('recommend', 'Recomendación'),
    'ACTIVACION': ('activation', 'Activación'),
}


def requiere_login(view_func):
    """Exige sesión autenticada para vistas HTML y endpoints API de App."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        uid = request.session.get('usuario_id')
        if not uid or not Usuario.objects.filter(id=uid).exists():
            if request.path.startswith('/api/'):
                return JsonResponse({'error': 'Autenticación requerida'}, status=401)
            login_url = reverse('login')
            return redirect(f'{login_url}?next={quote(request.get_full_path())}')
        return view_func(request, *args, **kwargs)

    return _wrapped


def _obtener_contexto_invernadero(fecha_ref: datetime | None = None) -> tuple[Invernadero, Parametro, dict[str, str]]:
    inv = Invernadero.objects.select_related('cultivo', 'cultivo__parametro').first()
    if inv is None or inv.cultivo is None:
        inv = asegurar_datos_iniciales(fecha_ref)
        inv = Invernadero.objects.select_related('cultivo', 'cultivo__parametro').get(id=inv.id)
    param = getattr(inv.cultivo, 'parametro', None)
    if param is None:
        param = Parametro.objects.first()
    mecanismos = {m.tipo: m.estado for m in Mecanismo.objects.filter(invernadero=inv)}
    return inv, param, mecanismos


def _formatear_fecha_es(dt: datetime) -> str:
    return f'{DIAS_ES[dt.weekday()].capitalize()}, {dt.day:02d} de {MESES_ES[dt.month - 1]} de {dt.year}'


def login_view(request):
    """Pantalla de ingreso y registro de operadores."""
    if request.session.get('usuario_id') and Usuario.objects.filter(id=request.session['usuario_id']).exists():
        return redirect('monitor')

    asegurar_datos_iniciales()
    error = None
    mensaje = None
    next_url = request.GET.get('next') or request.POST.get('next') or reverse('monitor')
    if not str(next_url).startswith('/') or str(next_url).startswith('//'):
        next_url = reverse('monitor')

    if request.method == 'POST':
        accion = request.POST.get('accion', 'login')
        username = (request.POST.get('username') or '').strip()
        contrasena = request.POST.get('contrasena') or ''

        if not username or not contrasena:
            error = 'Ingresá usuario y contraseña.'
        elif accion == 'registro':
            if Usuario.objects.filter(username=username).exists():
                error = 'El nombre de usuario ya está registrado.'
            elif len(contrasena) < 4:
                error = 'La contraseña debe tener al menos 4 caracteres.'
            else:
                usuario = registrar_usuario(username, contrasena)
                request.session['usuario_id'] = usuario.id
                request.session['usuario_nombre'] = usuario.username
                return redirect(next_url)
        else:
            usuario = validar_usuario(username, contrasena)
            if usuario is None:
                error = 'Usuario o contraseña incorrectos.'
            else:
                request.session['usuario_id'] = usuario.id
                request.session['usuario_nombre'] = usuario.username
                return redirect(next_url)

    return render(request, 'pages/login.html', {
        'error': error,
        'mensaje': mensaje,
        'next': next_url,
    })


def logout_view(request):
    request.session.flush()
    return redirect('login')


@requiere_login
def monitor_view(request):
    get_simulator()
    return render(request, 'pages/monitor.html')


@requiere_login
def historial_view(request):
    get_simulator()
    return render(request, 'pages/historial.html')


@requiere_login
def alertas_view(request):
    get_simulator()
    return render(request, 'pages/alertas.html')


@requiere_login
def reportes_view(request):
    sim = get_simulator()
    hoy_sim = sim.instante.date().isoformat()
    desde_def = (sim.instante.date() - timedelta(days=6)).isoformat()
    return render(request, 'pages/reportes.html', {
        'fecha_desde_defecto': desde_def,
        'fecha_hasta_defecto': hoy_sim,
    })


@requiere_login
def configuracion_view(request):
    get_simulator()
    return render(request, 'pages/configuracion.html')


@requiere_login
def acerca_de_view(request):
    sim = get_simulator()
    inv, param, mecanismos = _obtener_contexto_invernadero(sim.instante)
    return render(request, 'pages/acerca_de.html', {
        'invernadero': inv,
        'parametro': param,
        'mecanismos': mecanismos,
        'hora_simulada': sim.instante.strftime('%d/%m/%Y %H:%M:%S'),
    })


def _series_monitor_por_rango(inv_id: int, instante: datetime):
    def _build_set(qs_temp, qs_rad, qs_viento, fmt_label: str):
        t_list = list(qs_temp)
        r_list = list(qs_rad)
        v_list = list(qs_viento)
        return {
            'temperatura': {
                'labels': [x.fecha.strftime(fmt_label) for x in t_list],
                'values': [round(x.grados, 1) for x in t_list],
            },
            'radiacion': {
                'labels': [x.fecha.strftime(fmt_label) for x in r_list],
                'values': [round(x.valor) for x in r_list],
            },
            'viento': {
                'labels': [x.fecha.strftime(fmt_label) for x in v_list],
                'values': [round(x.valor, 1) for x in v_list],
            },
        }

    # 1. HOY (mismo día simulado)
    ini_hoy = datetime.combine(instante.date(), time.min)
    t_hoy = HistorialTemperatura.objects.filter(invernadero_id=inv_id, fecha__gte=ini_hoy, fecha__lte=instante).order_by('fecha')
    r_hoy = HistorialRadiacion.objects.filter(invernadero_id=inv_id, fecha__gte=ini_hoy, fecha__lte=instante).order_by('fecha')
    v_hoy = HistorialViento.objects.filter(invernadero_id=inv_id, fecha__gte=ini_hoy, fecha__lte=instante).order_by('fecha')
    # Limitar a los últimos 48 puntos para legibilidad
    hoy_data = _build_set(list(t_hoy)[-48:], list(r_hoy)[-48:], list(v_hoy)[-48:], '%H:%M')

    # 2. ÚLTIMAS 24H
    ini_24 = instante - timedelta(hours=24)
    t_24 = HistorialTemperatura.objects.filter(invernadero_id=inv_id, fecha__gte=ini_24, fecha__lte=instante).order_by('fecha')
    r_24 = HistorialRadiacion.objects.filter(invernadero_id=inv_id, fecha__gte=ini_24, fecha__lte=instante).order_by('fecha')
    v_24 = HistorialViento.objects.filter(invernadero_id=inv_id, fecha__gte=ini_24, fecha__lte=instante).order_by('fecha')
    data_24h = _build_set(list(t_24)[-60:], list(r_24)[-60:], list(v_24)[-60:], '%H:%M')

    # 3. ÚLTIMOS 7 DÍAS (máximos/promedios diarios)
    ini_7d = datetime.combine(instante.date() - timedelta(days=6), time.min)
    t_7 = HistorialTemperatura.objects.filter(invernadero_id=inv_id, fecha__gte=ini_7d, fecha__lte=instante).order_by('fecha')
    r_7 = HistorialRadiacion.objects.filter(invernadero_id=inv_id, fecha__gte=ini_7d, fecha__lte=instante).order_by('fecha')
    v_7 = HistorialViento.objects.filter(invernadero_id=inv_id, fecha__gte=ini_7d, fecha__lte=instante).order_by('fecha')

    def _agrupar_max_dia(items, attr):
        por_dia = defaultdict(list)
        for it in items:
            por_dia[it.fecha.date()].append(getattr(it, attr))
        labels, vals = [], []
        for offset in range(6, -1, -1):
            d = instante.date() - timedelta(days=offset)
            if d in por_dia:
                labels.append(DIAS_ES[d.weekday()].capitalize())
                vals.append(round(max(por_dia[d]), 1))
        return {'labels': labels, 'values': vals}

    data_7d = {
        'temperatura': _agrupar_max_dia(t_7, 'grados'),
        'radiacion': _agrupar_max_dia(r_7, 'valor'),
        'viento': _agrupar_max_dia(v_7, 'valor'),
    }

    return {'hoy': hoy_data, '24h': data_24h, '7d': data_7d}


@requiere_login
def api_monitor(request):
    sim = get_simulator()
    med = sim.medicion_actual()
    inv, param, mecanismos = _obtener_contexto_invernadero(med.instante)
    eval_estado = obtener_evaluador().estado_resumen(med.instante)

    clima_actual = 'NORMAL'
    for ev in sim.agenda.todos():
        if hasattr(ev, 'tipo') and ev.activo_en(med.instante):
            clima_actual = ev.tipo.name
            break

    pronostico_hoy = HistorialClima.objects.filter(
        invernadero=inv,
        es_pronostico=True,
        fecha__date=med.instante.date(),
    ).first()

    alertas_qs = list(Alerta.objects.filter(invernadero=inv).order_by('-fecha')[:20])
    notificaciones = []
    for a in alertas_qs:
        tipo_front, tag = TIPO_ALERTA_FRONT.get(a.categoria, ('alert', 'Alerta'))
        notificaciones.append({
            'id': a.id,
            'type': tipo_front,
            'tag': tag,
            'nivel': a.nivel,
            'title': a.titulo or a.variable,
            'time': a.fecha.strftime('%H:%M'),
            'fecha': a.fecha.strftime('%d/%m %H:%M'),
            'unread': not a.resuelta,
            'detail': a.descripcion,
        })

    alerta_banner = next((a for a in alertas_qs if a.categoria == 'ALERTA' and not a.resuelta), None)
    if alerta_banner:
        banner = {
            'nivel': alerta_banner.nivel,
            'titulo': alerta_banner.titulo or f'Alerta de {alerta_banner.variable}',
            'badge': 'CRÍTICO' if alerta_banner.nivel == 'CRITICO' else 'ALERTA',
            'descripcion': alerta_banner.descripcion,
        }
    else:
        banner = {
            'nivel': 'INFO',
            'titulo': 'Estado del sistema: Condiciones dentro de parámetros óptimos',
            'badge': 'NORMAL',
            'descripcion': f'Monitoreando {inv.cultivo.nombre if inv.cultivo else "invernadero"} en modo {inv.get_modo_display().lower()}.',
        }

    ultimo_evento = alertas_qs[0].fecha.strftime('%H:%M') if alertas_qs else med.instante.strftime('%H:%M')

    return JsonResponse({
        'ok': True,
        'invernadero': {
            'id': inv.id,
            'nombre': inv.nombre,
            'modo': inv.modo,
            'cultivo': inv.cultivo.nombre if inv.cultivo else 'Sin cultivo',
        },
        'reloj': {
            'instante': med.instante.isoformat(),
            'fecha_texto': _formatear_fecha_es(med.instante),
            'hora_texto': med.instante.strftime('%H:%M:%S'),
            'hora_corta': med.instante.strftime('%H:%M'),
            'velocidad': round(sim.velocidad, 1),
            'pausado': sim.pausado,
        },
        'kpis': {
            'radiacion': round(med.rad_interna),
            'radiacion_externa': round(med.rad_externa),
            'temperatura': round(med.temp_interna, 1),
            'temperatura_externa': round(med.temp_externa, 1),
            'viento': round(med.viento_externo, 1),
            'viento_pronosticado_hoy': round(pronostico_hoy.viento_estimado, 1) if pronostico_hoy and pronostico_hoy.viento_estimado is not None else round(med.viento_externo, 1),
            'clima_codigo': clima_actual,
            'clima_etiqueta': ETIQUETAS_CLIMA.get(clima_actual, clima_actual),
            'cultivo': inv.cultivo.nombre if inv.cultivo else 'Sin cultivo',
            'modo': inv.modo,
            'ultimo_evento': ultimo_evento,
        },
        'banner': banner,
        'mecanismos': {
            'VENTILACION': {
                'estado': mecanismos.get('VENTILACION', 'APAGADO'),
                'activo': mecanismos.get('VENTILACION', 'APAGADO') == 'ENCENDIDO',
            },
            'MEDIA_SOMBRA': {
                'estado': mecanismos.get('MEDIA_SOMBRA', 'RECOGIDA'),
                'activo': mecanismos.get('MEDIA_SOMBRA', 'RECOGIDA') == 'DESPLEGADA',
            },
            'CORTINAS_LATERALES': {
                'estado': mecanismos.get('CORTINAS_LATERALES', 'CERRADAS'),
                'activo': mecanismos.get('CORTINAS_LATERALES', 'CERRADAS') == 'ABIERTAS',
            },
        },
        'evaluador': eval_estado,
        'parametros': {
            'temp_min': param.temp_min,
            'temp_max': param.temp_max,
            'rad_min': param.rad_min,
            'rad_max': param.rad_max,
            'viento_max': param.viento_max,
            'tiempo_persistencia_min': param.tiempo_persistencia_min,
        },
        'series': _series_monitor_por_rango(inv.id, med.instante),
        'notificaciones': notificaciones,
    })


@requiere_login
@csrf_exempt
def api_modo(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    sim = get_simulator()
    instante = sim.instante
    inv, _, _ = _obtener_contexto_invernadero(instante)

    try:
        payload = json.loads(request.body.decode('utf-8'))
        modo_raw = str(payload.get('modo', 'AUTOMATICO')).upper()
        nuevo_modo = 'AUTOMATICO' if modo_raw in ('AUTO', 'AUTOMATICO') else 'MANUAL'
    except Exception as e:
        return JsonResponse({'error': f'JSON inválido: {e}'}, status=400)

    cambiar_modo_invernadero(inv.id, nuevo_modo, fecha=instante)
    registrar_alerta(
        id_invernadero=inv.id,
        variable='MODO',
        valor=1.0 if nuevo_modo == 'AUTOMATICO' else 0.0,
        nivel='INFO',
        categoria='ACTIVACION',
        titulo=f'Modo {"Automático" if nuevo_modo == "AUTOMATICO" else "Manual"} activado',
        descripcion=(
            f'[{instante:%H:%M:%S}] El operador cambió el modo de operación a {nuevo_modo}.'
        ),
        fecha=instante,
    )
    if nuevo_modo == 'AUTOMATICO':
        obtener_evaluador().evaluar(sim.medicion_actual(), sim=sim, invernadero_id=inv.id)

    return JsonResponse({'ok': True, 'modo': nuevo_modo})


@requiere_login
@csrf_exempt
def api_mecanismo(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    sim = get_simulator()
    instante = sim.instante
    inv, _, _ = _obtener_contexto_invernadero(instante)

    if inv.modo != 'MANUAL':
        return JsonResponse({'error': 'Cambiá a modo Manual para operar mecanismos directamente.'}, status=400)

    try:
        payload = json.loads(request.body.decode('utf-8'))
        mec_raw = str(payload.get('mecanismo', '')).upper()
        activo = payload.get('activo')
        estado_raw = str(payload.get('estado', '')).upper()
    except Exception as e:
        return JsonResponse({'error': f'JSON inválido: {e}'}, status=400)

    alias = {
        'TURBINES': 'VENTILACION',
        'VENTILACION': 'VENTILACION',
        'SHADE': 'MEDIA_SOMBRA',
        'MEDIA_SOMBRA': 'MEDIA_SOMBRA',
        'CURTAINS': 'CORTINAS_LATERALES',
        'CORTINAS_LATERALES': 'CORTINAS_LATERALES',
    }
    tipo = alias.get(mec_raw)
    if not tipo:
        return JsonResponse({'error': 'Mecanismo no reconocido'}, status=400)

    if isinstance(activo, bool):
        encender = activo
    else:
        encender = estado_raw in ('ENCENDIDO', 'DESPLEGADA', 'ABIERTAS', 'ON', 'TRUE', '1')

    estados_canonicos = {
        'VENTILACION': 'ENCENDIDO' if encender else 'APAGADO',
        'MEDIA_SOMBRA': 'DESPLEGADA' if encender else 'RECOGIDA',
        'CORTINAS_LATERALES': 'ABIERTAS' if encender else 'CERRADAS',
    }
    nuevo_estado = estados_canonicos[tipo]

    cambiar_mecanismo_por_tipo(
        id_invernadero=inv.id,
        tipo=tipo,
        nuevo_estado=nuevo_estado,
        origen='MANUAL',
        fecha=instante,
    )
    sincronizar_mecanismo_en_simulador(sim, tipo, nuevo_estado)
    registrar_alerta(
        id_invernadero=inv.id,
        variable=tipo,
        valor=1.0 if encender else 0.0,
        nivel='INFO',
        categoria='ACTIVACION',
        titulo=f'Activación manual: {tipo.replace("_", " ").title()} -> {nuevo_estado}',
        descripcion=(
            f'[{instante:%H:%M:%S}] Activación manual desde Monitor: '
            f'{tipo.replace("_", " ").lower()} pasó a estado {nuevo_estado}.'
        ),
        fecha=instante,
    )

    return JsonResponse({'ok': True, 'tipo': tipo, 'estado': nuevo_estado, 'activo': encender})


@requiere_login
@csrf_exempt
def api_alertas_leer(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    inv, _, _ = _obtener_contexto_invernadero(obtener_instante_actual())
    cantidad = marcar_alertas_leidas(inv.id)
    return JsonResponse({'ok': True, 'marcadas': cantidad})


@requiere_login
def api_historial(request):
    sim = get_simulator()
    instante = sim.instante
    inv, param, _ = _obtener_contexto_invernadero(instante)

    fecha_param = request.GET.get('fecha')
    rango = request.GET.get('rango', 'hour')
    try:
        fecha_ref = date.fromisoformat(fecha_param) if fecha_param else instante.date()
    except ValueError:
        fecha_ref = instante.date()

    # Pronóstico extendido de 8 días desde BD (incluye viento_estimado)
    pronostico_qs = list(
        HistorialClima.objects.filter(invernadero=inv, es_pronostico=True).order_by('fecha')[:8]
    )
    pronostico = [
        {
            'fecha': p.fecha.strftime('%Y-%m-%d'),
            'dia': 'Hoy' if idx == 0 else DIAS_ES[p.fecha.weekday()],
            'estado': p.estado,
            'etiqueta': ETIQUETAS_CLIMA.get(p.estado, p.estado),
            'temp_max': round(p.temp_max_pronostico if p.temp_max_pronostico is not None else (p.temp_externa or 22.0), 1),
            'temp_min': round(p.temp_min_pronostico if p.temp_min_pronostico is not None else 15.0, 1),
            'prob_lluvia': p.probabilidad_lluvia,
            'viento_kmh': round(p.viento_estimado, 1) if p.viento_estimado is not None else 12.0,
        }
        for idx, p in enumerate(pronostico_qs)
    ]

    # Series históricas de temperatura, radiación y viento
    if rango == 'day':
        dt_ini = datetime.combine(fecha_ref - timedelta(days=6), time.min)
        dt_fin = datetime.combine(fecha_ref, time.max)
        t_qs = HistorialTemperatura.objects.filter(invernadero=inv, fecha__range=(dt_ini, dt_fin)).order_by('fecha')
        r_qs = HistorialRadiacion.objects.filter(invernadero=inv, fecha__range=(dt_ini, dt_fin)).order_by('fecha')
        v_qs = HistorialViento.objects.filter(invernadero=inv, fecha__range=(dt_ini, dt_fin)).order_by('fecha')

        def _prom_diario(qs, attr):
            buckets = defaultdict(list)
            for item in qs:
                buckets[item.fecha.date()].append(getattr(item, attr))
            etiquetas, datos = [], []
            for d in sorted(buckets):
                etiquetas.append(f'{DIAS_ES[d.weekday()]} {d:%d/%m}')
                datos.append(round(sum(buckets[d]) / len(buckets[d]), 1))
            return {'etiquetas': etiquetas, 'datos': datos}

        temp_serie = _prom_diario(t_qs, 'grados')
        rad_serie = _prom_diario(r_qs, 'valor')
        viento_serie = _prom_diario(v_qs, 'valor')
    else:
        dt_ini = datetime.combine(fecha_ref, time.min)
        dt_fin = datetime.combine(fecha_ref, time.max)
        t_qs = list(HistorialTemperatura.objects.filter(invernadero=inv, fecha__range=(dt_ini, dt_fin)).order_by('fecha'))
        r_qs = list(HistorialRadiacion.objects.filter(invernadero=inv, fecha__range=(dt_ini, dt_fin)).order_by('fecha'))
        v_qs = list(HistorialViento.objects.filter(invernadero=inv, fecha__range=(dt_ini, dt_fin)).order_by('fecha'))

        if rango == 'hour':
            def _prom_horario(qs, attr):
                buckets = defaultdict(list)
                for item in qs:
                    buckets[item.fecha.strftime('%H:00')].append(getattr(item, attr))
                etiquetas = sorted(buckets)
                datos = [round(sum(buckets[h]) / len(buckets[h]), 1) for h in etiquetas]
                return {'etiquetas': etiquetas, 'datos': datos}

            temp_serie = _prom_horario(t_qs, 'grados')
            rad_serie = _prom_horario(r_qs, 'valor')
            viento_serie = _prom_horario(v_qs, 'valor')
        else:
            temp_serie = {
                'etiquetas': [x.fecha.strftime('%H:%M') for x in t_qs[-144:]],
                'datos': [round(x.grados, 1) for x in t_qs[-144:]],
            }
            rad_serie = {
                'etiquetas': [x.fecha.strftime('%H:%M') for x in r_qs[-144:]],
                'datos': [round(x.valor) for x in r_qs[-144:]],
            }
            viento_serie = {
                'etiquetas': [x.fecha.strftime('%H:%M') for x in v_qs[-144:]],
                'datos': [round(x.valor, 1) for x in v_qs[-144:]],
            }

    # Historial real de activaciones diarias (media sombra y cortinas laterales)
    ini_act = datetime.combine(fecha_ref - timedelta(days=29), time.min)
    fin_act = datetime.combine(fecha_ref, time.max)
    evs_mec = (
        HistorialMecanismo.objects.select_related('mecanismo')
        .filter(mecanismo__invernadero=inv, fecha__range=(ini_act, fin_act))
        .order_by('fecha')
    )
    act_sombra = defaultdict(int)
    act_cortinas = defaultdict(int)
    for ev in evs_mec:
        d = ev.fecha.date()
        if ev.mecanismo.tipo == 'MEDIA_SOMBRA' and ev.a_que_estado_paso == 'DESPLEGADA':
            act_sombra[d] += 1
        elif ev.mecanismo.tipo == 'CORTINAS_LATERALES':
            act_cortinas[d] += 1

    activaciones = []
    for offset in range(29, -1, -1):
        d = fecha_ref - timedelta(days=offset)
        ms = act_sombra.get(d, 0)
        cl = act_cortinas.get(d, 0)
        activaciones.append({
            'fechaCorta': f'{d:%d/%m}',
            'fechaCompleta': f'{DIAS_ES[d.weekday()]} {d:%d/%m/%Y}',
            'media_sombra': ms,
            'cortinas': cl,
            'cantidad': ms + cl,
        })

    return JsonResponse({
        'ok': True,
        'fecha_referencia': fecha_ref.isoformat(),
        'hora_simulada': instante.strftime('%H:%M:%S'),
        'rango': rango,
        'ubicacion': inv.nombre,
        'parametros': {
            'temp_min': param.temp_min,
            'temp_max': param.temp_max,
            'rad_min': param.rad_min,
            'rad_max': param.rad_max,
            'viento_max': param.viento_max,
        },
        'pronostico': pronostico,
        'series': {
            'temperatura': temp_serie,
            'radiacion': rad_serie,
            'viento': viento_serie,
        },
        'activaciones': activaciones,
    })


@requiere_login
def api_alertas(request):
    sim = get_simulator()
    inv, _, _ = _obtener_contexto_invernadero(sim.instante)

    q = (request.GET.get('q') or '').strip()
    tipo = (request.GET.get('tipo') or 'all').lower()
    desde_str = (request.GET.get('desde') or '').strip()
    hasta_str = (request.GET.get('hasta') or '').strip()

    qs = Alerta.objects.filter(invernadero=inv)

    mapa_cat = {'alert': 'ALERTA', 'recommend': 'RECOMENDACION', 'activation': 'ACTIVACION'}
    if tipo in mapa_cat:
        qs = qs.filter(categoria=mapa_cat[tipo])

    if q:
        qs = qs.filter(Q(titulo__icontains=q) | Q(descripcion__icontains=q) | Q(variable__icontains=q))

    if desde_str:
        try:
            qs = qs.filter(fecha__gte=datetime.fromisoformat(desde_str))
        except ValueError:
            pass
    if hasta_str:
        try:
            qs = qs.filter(fecha__lte=datetime.fromisoformat(hasta_str))
        except ValueError:
            pass

    iconos = {
        'ALERTA': '⚠️',
        'RECOMENDACION': '💡',
        'ACTIVACION': '⚡',
    }
    datos = []
    for a in qs.order_by('-fecha')[:100]:
        tipo_front, tag = TIPO_ALERTA_FRONT.get(a.categoria, ('alert', 'Alerta'))
        datos.append({
            'id': a.id,
            'type': tipo_front,
            'icon': iconos.get(a.categoria, '🔔'),
            'tag': tag,
            'nivel': a.nivel,
            'variable': a.variable,
            'titulo': a.titulo or a.variable,
            'descripcion': a.descripcion,
            'fecha_iso': a.fecha.isoformat(timespec='minutes'),
            'fecha_texto': a.fecha.strftime('%d/%m/%Y %H:%M'),
            'hora_texto': a.fecha.strftime('%H:%M'),
            'resuelta': a.resuelta,
        })

    return JsonResponse({
        'ok': True,
        'hora_simulada': sim.instante.strftime('%d/%m/%Y %H:%M:%S'),
        'total': len(datos),
        'notificaciones': datos,
    })


@requiere_login
@csrf_exempt
def api_configuracion(request):
    sim = get_simulator()
    instante = sim.instante
    inv, param, _ = _obtener_contexto_invernadero(instante)

    if request.method == 'GET':
        cultivos = []
        for c in Cultivo.objects.select_related('parametro').order_by('nombre'):
            p = getattr(c, 'parametro', None)
            cultivos.append({
                'id': c.id,
                'nombre': c.nombre,
                'recomendaciones': c.recomendaciones or '',
                'parametros': {
                    'temp_min': p.temp_min if p else 16.0,
                    'temp_max': p.temp_max if p else 28.0,
                    'rad_min': p.rad_min if p else 300.0,
                    'rad_max': p.rad_max if p else 750.0,
                    'viento_max': p.viento_max if p else 40.0,
                    'tiempo_persistencia_min': p.tiempo_persistencia_min if p else 5,
                },
            })
        return JsonResponse({
            'ok': True,
            'invernadero': {
                'id': inv.id,
                'nombre': inv.nombre,
                'modo': inv.modo,
                'cultivo_id': inv.cultivo_id,
                'cultivo_nombre': inv.cultivo.nombre if inv.cultivo else '',
            },
            'parametros': {
                'temp_min': param.temp_min,
                'temp_max': param.temp_max,
                'rad_min': param.rad_min,
                'rad_max': param.rad_max,
                'viento_max': param.viento_max,
                'tiempo_persistencia_min': param.tiempo_persistencia_min,
            },
            'cultivos': cultivos,
        })

    if request.method == 'POST':
        try:
            payload = json.loads(request.body.decode('utf-8'))
            cultivo_id = int(payload.get('cultivo_id') or inv.cultivo_id)
            temp_min = float(payload['temp_min'])
            temp_max = float(payload['temp_max'])
            rad_min = float(payload['rad_min'])
            rad_max = float(payload['rad_max'])
            viento_max = float(payload['viento_max'])
            persistencia_min = int(payload.get('tiempo_persistencia_min', 5))
            modo = str(payload.get('modo', inv.modo)).upper()
        except Exception as e:
            return JsonResponse({'error': f'Datos inválidos: {e}'}, status=400)

        if temp_min >= temp_max or rad_min >= rad_max or viento_max <= 0:
            return JsonResponse({'error': 'Los límites mínimos deben ser menores a los máximos y el viento > 0.'}, status=400)
        if modo not in ('AUTOMATICO', 'MANUAL'):
            return JsonResponse({'error': 'Modo de operación inválido.'}, status=400)

        seleccionar_cultivo_invernadero(inv.id, cultivo_id)
        cambiar_modo_invernadero(inv.id, modo, fecha=instante)
        param_act = establecer_parametros_cultivo(
            id_cultivo=cultivo_id,
            temp_min=temp_min,
            temp_max=temp_max,
            rad_min=rad_min,
            rad_max=rad_max,
            viento_max=viento_max,
            persistencia_min=persistencia_min,
            fecha=instante,
        )
        registrar_alerta(
            id_invernadero=inv.id,
            variable='PARAMETROS',
            valor=viento_max,
            nivel='INFO',
            categoria='ACTIVACION',
            titulo=f'Configuración actualizada ({param_act.cultivo.nombre})',
            descripcion=(
                f'[{instante:%H:%M:%S}] Umbrales actualizados: Temp {temp_min}-{temp_max} °C, '
                f'Rad {rad_min:.0f}-{rad_max:.0f} W/m², Viento máx {viento_max:.0f} km/h, '
                f'Persistencia {persistencia_min} min, Modo {modo}.'
            ),
            fecha=instante,
        )
        if modo == 'AUTOMATICO':
            obtener_evaluador().evaluar(sim.medicion_actual(), sim=sim, invernadero_id=inv.id)

        return JsonResponse({'ok': True, 'mensaje': 'Configuración guardada correctamente en la base de datos.'})

    return JsonResponse({'error': 'Método no permitido'}, status=405)


@requiere_login
@csrf_exempt
def api_cultivos(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    sim = get_simulator()
    instante = sim.instante
    try:
        payload = json.loads(request.body.decode('utf-8'))
        nombre = (payload.get('nombre') or '').strip()
        recomendaciones = (payload.get('recomendaciones') or '').strip()
    except Exception as e:
        return JsonResponse({'error': f'JSON inválido: {e}'}, status=400)

    if not nombre:
        return JsonResponse({'error': 'Ingresá un nombre para el cultivo.'}, status=400)
    if Cultivo.objects.filter(nombre__iexact=nombre).exists():
        return JsonResponse({'error': 'Este cultivo ya se encuentra registrado.'}, status=400)

    cultivo = registrar_cultivo(nombre, recomendaciones)
    param = establecer_parametros_cultivo(
        id_cultivo=cultivo.id,
        temp_min=float(payload.get('temp_min', 16.0)),
        temp_max=float(payload.get('temp_max', 28.0)),
        rad_min=float(payload.get('rad_min', 300.0)),
        rad_max=float(payload.get('rad_max', 750.0)),
        viento_max=float(payload.get('viento_max', 40.0)),
        persistencia_min=int(payload.get('tiempo_persistencia_min', 5)),
        fecha=instante,
    )
    return JsonResponse({
        'ok': True,
        'cultivo': {
            'id': cultivo.id,
            'nombre': cultivo.nombre,
            'parametros': {
                'temp_min': param.temp_min,
                'temp_max': param.temp_max,
                'rad_min': param.rad_min,
                'rad_max': param.rad_max,
                'viento_max': param.viento_max,
                'tiempo_persistencia_min': param.tiempo_persistencia_min,
            },
        },
    })


@requiere_login
def api_reportes(request):
    inv, _, _ = _obtener_contexto_invernadero(obtener_instante_actual())
    reps = Reporte.objects.filter(invernadero=inv).order_by('-fecha_generacion')
    return JsonResponse({
        'ok': True,
        'reportes': [
            {
                'id': r.id,
                'nombre': r.nombre,
                'tipo': r.tipo,
                'periodo': f'{r.fecha_desde:%d/%m/%Y} - {r.fecha_hasta:%d/%m/%Y}',
                'fecha_generacion': r.fecha_generacion.strftime('%d/%m/%Y %H:%M'),
                'filas': r.filas,
                'url_descarga': reverse('descargar_reporte', args=[r.id]),
            }
            for r in reps
        ],
    })


@requiere_login
@csrf_exempt
def api_generar_reporte(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    sim = get_simulator()
    instante = sim.instante
    inv, _, _ = _obtener_contexto_invernadero(instante)

    try:
        payload = json.loads(request.body.decode('utf-8'))
        f_desde = date.fromisoformat(payload['fecha_desde'])
        f_hasta = date.fromisoformat(payload['fecha_hasta'])
        tipo = str(payload.get('tipo', 'HISTORICO_CONSOLIDADO')).upper()
    except Exception as e:
        return JsonResponse({'error': f'Rango de fechas inválido: {e}'}, status=400)

    if f_desde > f_hasta:
        return JsonResponse({'error': 'La fecha de inicio no puede ser posterior a la fecha final.'}, status=400)
    if tipo not in ('HISTORICO_CONSOLIDADO', 'DETALLE_EVENTOS'):
        tipo = 'HISTORICO_CONSOLIDADO'

    rep = generar_reporte_csv(
        id_invernadero=inv.id,
        fecha_desde=f_desde,
        fecha_hasta=f_hasta,
        fecha_generacion=instante,
        tipo=tipo,
    )
    return JsonResponse({
        'ok': True,
        'reporte': {
            'id': rep.id,
            'nombre': rep.nombre,
            'tipo': rep.tipo,
            'periodo': f'{rep.fecha_desde:%d/%m/%Y} - {rep.fecha_hasta:%d/%m/%Y}',
            'fecha_generacion': rep.fecha_generacion.strftime('%d/%m/%Y %H:%M'),
            'filas': rep.filas,
            'url_descarga': reverse('descargar_reporte', args=[rep.id]),
        },
    })


@requiere_login
def descargar_reporte(request, reporte_id: int):
    rep = Reporte.objects.filter(id=reporte_id).first()
    if rep is None:
        raise Http404('Reporte no encontrado')
    ruta = Path(rep.ruta_archivo)
    if not ruta.exists():
        raise Http404('Archivo de reporte no disponible en disco')
    return FileResponse(
        open(ruta, 'rb'),
        as_attachment=True,
        filename=rep.nombre,
        content_type='text/csv; charset=utf-8',
    )


@requiere_login
@csrf_exempt
def api_eliminar_reporte(request, reporte_id: int):
    if request.method not in ('POST', 'DELETE'):
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    eliminado = eliminar_reporte(reporte_id)
    if not eliminado:
        return JsonResponse({'error': 'Reporte no encontrado'}, status=404)
    return JsonResponse({'ok': True})
