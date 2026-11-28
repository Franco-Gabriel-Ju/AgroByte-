import csv
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from .models import (
    Alerta,
    Cultivo,
    HistorialClima,
    HistorialMecanismo,
    HistorialParametro,
    HistorialRadiacion,
    HistorialTemperatura,
    HistorialViento,
    Invernadero,
    Mecanismo,
    Parametro,
    Reporte,
    Usuario,
)


CULTIVOS_POR_DEFECTO = [
    {
        'nombre': 'Lechuga Morada',
        'recomendaciones': 'Mantener temperatura entre 16 °C y 28 °C. Proteger con media sombra sobre 750 W/m² y cerrar cortinas con vientos > 40 km/h.',
        'temp_min': 16.0,
        'temp_max': 28.0,
        'rad_min': 300.0,
        'rad_max': 750.0,
        'viento_max': 40.0,
        'tiempo_persistencia_min': 5,
    },
    {
        'nombre': 'Tomate Cherry',
        'recomendaciones': 'Cultivo cálido tolerante hasta 30 °C y 850 W/m². Resguardar de vientos superiores a 45 km/h.',
        'temp_min': 18.0,
        'temp_max': 30.0,
        'rad_min': 350.0,
        'rad_max': 850.0,
        'viento_max': 45.0,
        'tiempo_persistencia_min': 5,
    },
    {
        'nombre': 'Albahaca',
        'recomendaciones': 'Sensible a corrientes de viento fuerte (> 35 km/h) y frío por debajo de 17 °C.',
        'temp_min': 17.0,
        'temp_max': 29.0,
        'rad_min': 320.0,
        'rad_max': 780.0,
        'viento_max': 35.0,
        'tiempo_persistencia_min': 5,
    },
]

MECANISMOS_POR_DEFECTO = {
    'MEDIA_SOMBRA': 'RECOGIDA',
    'CORTINAS_LATERALES': 'CERRADAS',
    'VENTILACION': 'APAGADO',
}

ETIQUETAS_CLIMA = dict(HistorialClima.ESTADOS_CLIMA)


def asegurar_datos_iniciales(fecha_ref: datetime | None = None) -> Invernadero:
    """Garantiza usuarios, cultivos, parámetros, invernadero y mecanismos iniciales en BD."""
    fecha = fecha_ref or timezone.now()
    with transaction.atomic():
        if not Usuario.objects.exists():
            registrar_usuario('admin', 'admin123')
            registrar_usuario('operador', 'nona2026')

        cultivos_creados = {}
        for item in CULTIVOS_POR_DEFECTO:
            cultivo, _ = Cultivo.objects.get_or_create(
                nombre=item['nombre'],
                defaults={'recomendaciones': item['recomendaciones']},
            )
            cultivos_creados[item['nombre']] = cultivo
            if not Parametro.objects.filter(cultivo=cultivo).exists():
                establecer_parametros_cultivo(
                    id_cultivo=cultivo.id,
                    temp_min=item['temp_min'],
                    temp_max=item['temp_max'],
                    rad_min=item['rad_min'],
                    rad_max=item['rad_max'],
                    viento_max=item['viento_max'],
                    persistencia_min=item['tiempo_persistencia_min'],
                    fecha=fecha,
                )

        inv = Invernadero.objects.first()
        if inv is None:
            inv = Invernadero.objects.create(
                nombre='Invernadero Nona Olimpia - Módulo 1',
                modo='AUTOMATICO',
                cultivo=cultivos_creados['Lechuga Morada'],
            )
        elif inv.cultivo is None:
            inv.cultivo = cultivos_creados['Lechuga Morada']
            inv.save(update_fields=['cultivo'])

        for tipo, estado_def in MECANISMOS_POR_DEFECTO.items():
            Mecanismo.objects.get_or_create(
                invernadero=inv,
                tipo=tipo,
                defaults={'estado': estado_def},
            )

        return inv


@transaction.atomic
def reiniciar_datos_simulacion(
    id_invernadero: int,
    estados_iniciales: dict[str, str] | None = None,
    restaurar_modo_auto: bool = False,
) -> None:
    """Limpia historiales de simulación y alertas de un invernadero y sincroniza sus mecanismos."""
    HistorialTemperatura.objects.filter(invernadero_id=id_invernadero).delete()
    HistorialRadiacion.objects.filter(invernadero_id=id_invernadero).delete()
    HistorialViento.objects.filter(invernadero_id=id_invernadero).delete()
    HistorialClima.objects.filter(invernadero_id=id_invernadero).delete()
    HistorialMecanismo.objects.filter(mecanismo__invernadero_id=id_invernadero).delete()
    Alerta.objects.filter(invernadero_id=id_invernadero).delete()

    estados = estados_iniciales if estados_iniciales is not None else MECANISMOS_POR_DEFECTO
    for tipo, estado in estados.items():
        actualizados = Mecanismo.objects.filter(
            invernadero_id=id_invernadero,
            tipo=tipo,
        ).update(estado=estado)
        if not actualizados:
            Mecanismo.objects.create(
                invernadero_id=id_invernadero,
                tipo=tipo,
                estado=estado,
            )

    if restaurar_modo_auto:
        Invernadero.objects.filter(id=id_invernadero).update(modo='AUTOMATICO')


def registrar_cultivo(nombre: str, recomendaciones: str = '') -> Cultivo:
    cultivo, _ = Cultivo.objects.update_or_create(
        nombre=nombre.strip(),
        defaults={'recomendaciones': recomendaciones},
    )
    return cultivo


def registrar_lectura_sensores(
    id_invernadero: int,
    grados: float,
    radiacion: float,
    viento: float = 0.0,
    temp_externa: float | None = None,
    rad_externa: float | None = None,
    fecha: datetime | None = None,
):
    fecha_reg = fecha or timezone.now()
    with transaction.atomic():
        reg_temp = HistorialTemperatura.objects.create(
            invernadero_id=id_invernadero,
            grados=round(float(grados), 2),
            temp_externa=round(float(temp_externa), 2) if temp_externa is not None else None,
            fecha=fecha_reg,
        )
        reg_rad = HistorialRadiacion.objects.create(
            invernadero_id=id_invernadero,
            valor=round(float(radiacion), 2),
            rad_externa=round(float(rad_externa), 2) if rad_externa is not None else None,
            fecha=fecha_reg,
        )
        reg_viento = HistorialViento.objects.create(
            invernadero_id=id_invernadero,
            valor=round(max(0.0, float(viento)), 2),
            fecha=fecha_reg,
        )
    return reg_temp, reg_rad, reg_viento


def registrar_clima(
    id_invernadero: int,
    estado: str,
    temp_externa: float | None = None,
    viento_estimado: float | None = None,
    prob_lluvia: int = 0,
    es_pronostico: bool = False,
    temp_min_pronostico: float | None = None,
    temp_max_pronostico: float | None = None,
    fecha: datetime | None = None,
) -> HistorialClima:
    return HistorialClima.objects.create(
        invernadero_id=id_invernadero,
        estado=estado,
        temp_externa=round(float(temp_externa), 2) if temp_externa is not None else None,
        viento_estimado=round(float(viento_estimado), 2) if viento_estimado is not None else None,
        temp_min_pronostico=round(float(temp_min_pronostico), 1) if temp_min_pronostico is not None else None,
        temp_max_pronostico=round(float(temp_max_pronostico), 1) if temp_max_pronostico is not None else None,
        probabilidad_lluvia=int(prob_lluvia),
        es_pronostico=es_pronostico,
        fecha=fecha or timezone.now(),
    )


def actualizar_pronostico_extendido(
    id_invernadero: int,
    fecha_base: datetime,
    clima_actual: str,
    temp_base: float,
    viento_base: float,
) -> list[HistorialClima]:
    """Genera/actualiza el pronóstico de 8 días en HistorialClima (incluye predicción de viento)."""
    ciclo_estados = [
        ('DESPEJADO', 5, 0.0, 0.0),
        ('PARCIALMENTE_NUBLADO', 20, -1.5, 5.0),
        ('SOL_INTENSO', 0, +3.0, -2.0),
        ('NUBLADO', 35, -2.5, 8.0),
        ('LLUVIA', 80, -4.0, 14.0),
        ('PARCIALMENTE_NUBLADO', 20, -1.0, 6.0),
        ('DESPEJADO', 5, +1.0, 1.0),
    ]
    prob_actual = {
        'NORMAL': 5,
        'DESPEJADO': 5,
        'SOL_INTENSO': 0,
        'NUBLADO': 30,
        'LLUVIA': 85,
        'TORMENTA': 90,
        'TORMENTA_ELECTRICA': 95,
        'FRIO_INTENSO': 15,
        'VENTISCA': 35,
        'GRANIZO': 95,
    }.get(clima_actual, 10)

    creados: list[HistorialClima] = []
    with transaction.atomic():
        HistorialClima.objects.filter(
            invernadero_id=id_invernadero,
            es_pronostico=True,
        ).delete()

        for offset in range(8):
            dia_dt = datetime.combine(fecha_base.date() + timedelta(days=offset), time(12, 0))
            if offset == 0:
                estado_dia = clima_actual if clima_actual in ETIQUETAS_CLIMA else 'NORMAL'
                prob = prob_actual
                tmax = round(max(temp_base, 14.0) + 2.5, 1)
                tmin = round(tmax - 7.5, 1)
                viento_dia = round(max(4.0, viento_base), 1)
            else:
                idx = (fecha_base.day + offset) % len(ciclo_estados)
                estado_dia, prob, dt_temp, dv_viento = ciclo_estados[idx]
                onda = math.sin((offset + fecha_base.day) * 0.7) * 1.5
                tmax = round(21.5 + dt_temp + onda, 1)
                tmin = round(tmax - 7.0, 1)
                viento_dia = round(max(6.0, 12.0 + dv_viento + abs(onda) * 2.0), 1)

            creados.append(
                HistorialClima.objects.create(
                    invernadero_id=id_invernadero,
                    estado=estado_dia,
                    temp_externa=round((tmax + tmin) / 2.0, 1),
                    viento_estimado=viento_dia,
                    temp_min_pronostico=tmin,
                    temp_max_pronostico=tmax,
                    probabilidad_lluvia=prob,
                    es_pronostico=True,
                    fecha=dia_dt,
                )
            )
    return creados


def registrar_alerta(
    id_invernadero: int,
    variable: str,
    valor: float,
    descripcion: str,
    fecha: datetime | None = None,
    nivel: str = 'ADVERTENCIA',
    categoria: str = 'ALERTA',
    titulo: str = '',
    umbral: float | None = None,
) -> Alerta:
    return Alerta.objects.create(
        invernadero_id=id_invernadero,
        variable=variable,
        valor_detectado=round(float(valor), 2),
        descripcion=descripcion,
        fecha=fecha or timezone.now(),
        nivel=nivel,
        categoria=categoria,
        titulo=titulo[:160],
        umbral=round(float(umbral), 2) if umbral is not None else None,
    )


def marcar_alertas_leidas(id_invernadero: int) -> int:
    return Alerta.objects.filter(invernadero_id=id_invernadero, leida=False).update(leida=True)


@transaction.atomic
def resolver_alertas_activas(
    id_invernadero: int,
    variable: str | None = None,
    fecha_resolucion: datetime | None = None,
    incluir_recomendaciones: bool = True,
) -> int:
    """Marca como resueltas las alertas abiertas de categoría ALERTA (y opcionalmente RECOMENDACION)
    para un invernadero y variable dados, sin borrarlas del historial."""
    categorias = ['ALERTA', 'RECOMENDACION'] if incluir_recomendaciones else ['ALERTA']
    qs = Alerta.objects.filter(
        invernadero_id=id_invernadero,
        resuelta=False,
        categoria__in=categorias,
    )
    if variable is not None:
        qs = qs.filter(variable=variable)
    return qs.update(resuelta=True)


def establecer_parametros_cultivo(
    id_cultivo: int,
    temp_min: float,
    temp_max: float,
    rad_min: float,
    rad_max: float,
    viento_max: float = 40.0,
    persistencia_min: int = 5,
    fecha: datetime | None = None,
) -> Parametro:
    fecha_reg = fecha or timezone.now()
    with transaction.atomic():
        param, _ = Parametro.objects.update_or_create(
            cultivo_id=id_cultivo,
            defaults={
                'temp_min': float(temp_min),
                'temp_max': float(temp_max),
                'rad_min': float(rad_min),
                'rad_max': float(rad_max),
                'viento_max': float(viento_max),
                'tiempo_persistencia_min': max(1, int(persistencia_min)),
                'fecha_actualizacion': fecha_reg,
            },
        )
        HistorialParametro.objects.create(
            parametro=param,
            temp_min=float(temp_min),
            temp_max=float(temp_max),
            rad_min=float(rad_min),
            rad_max=float(rad_max),
            viento_max=float(viento_max),
            tiempo_persistencia_min=max(1, int(persistencia_min)),
            fecha=fecha_reg,
        )
    return param


def cambiar_estado_mecanismo(
    id_mecanismo: int,
    nuevo_estado: str,
    origen: str = 'AUTOMATICO',
    fecha: datetime | None = None,
) -> Mecanismo:
    fecha_reg = fecha or timezone.now()
    with transaction.atomic():
        mec = Mecanismo.objects.select_for_update().get(id=id_mecanismo)
        if mec.estado != nuevo_estado:
            mec.estado = nuevo_estado
            mec.save(update_fields=['estado'])
            HistorialMecanismo.objects.create(
                mecanismo=mec,
                a_que_estado_paso=nuevo_estado,
                origen=origen,
                fecha=fecha_reg,
            )
    return mec


def cambiar_mecanismo_por_tipo(
    id_invernadero: int,
    tipo: str,
    nuevo_estado: str,
    origen: str = 'AUTOMATICO',
    fecha: datetime | None = None,
) -> Mecanismo:
    with transaction.atomic():
        mec, creado = Mecanismo.objects.get_or_create(
            invernadero_id=id_invernadero,
            tipo=tipo,
            defaults={'estado': MECANISMOS_POR_DEFECTO.get(tipo, 'APAGADO')},
        )
        if creado and mec.estado == nuevo_estado:
            HistorialMecanismo.objects.create(
                mecanismo=mec,
                a_que_estado_paso=nuevo_estado,
                origen=origen,
                fecha=fecha or timezone.now(),
            )
            return mec
    return cambiar_estado_mecanismo(mec.id, nuevo_estado, origen=origen, fecha=fecha)


def cambiar_modo_invernadero(
    id_invernadero: int,
    nuevo_modo: str,
    fecha: datetime | None = None,
) -> Invernadero:
    with transaction.atomic():
        inv = Invernadero.objects.select_for_update().get(id=id_invernadero)
        inv.modo = nuevo_modo
        inv.save(update_fields=['modo'])
    return inv


def seleccionar_cultivo_invernadero(id_invernadero: int, id_cultivo: int) -> Invernadero:
    with transaction.atomic():
        inv = Invernadero.objects.select_for_update().get(id=id_invernadero)
        inv.cultivo_id = id_cultivo
        inv.save(update_fields=['cultivo'])
    return inv


def registrar_usuario(username: str, contrasena: str) -> Usuario:
    return Usuario.objects.create(
        username=username.strip(),
        contrasena=make_password(contrasena),
    )


def validar_usuario(username: str, contrasena: str) -> Usuario | None:
    usuario = Usuario.objects.filter(username=username.strip()).first()
    if usuario and check_password(contrasena, usuario.contrasena):
        return usuario
    return None


def obtener_temporada(fecha_date: date) -> str:
    """Temporada astronómica aproximada para hemisferio sur (Argentina)."""
    mes = fecha_date.month
    dia = fecha_date.day
    if (mes == 12 and dia >= 21) or mes in (1, 2) or (mes == 3 and dia < 21):
        return 'Verano'
    if (mes == 3 and dia >= 21) or mes in (4, 5) or (mes == 6 and dia < 21):
        return 'Otoño'
    if (mes == 6 and dia >= 21) or mes in (7, 8) or (mes == 9 and dia < 21):
        return 'Invierno'
    return 'Primavera'


def _contar_despliegues_diarios(eventos_mec) -> dict[str, dict[date, int]]:
    conteo = {
        'MEDIA_SOMBRA': defaultdict(int),
        'CORTINAS_LATERALES': defaultdict(int),
        'VENTILACION': defaultdict(int),
    }
    for ev in eventos_mec:
        d = ev.fecha.date()
        tipo = ev.mecanismo.tipo
        if tipo == 'MEDIA_SOMBRA' and ev.a_que_estado_paso == 'DESPLEGADA':
            conteo['MEDIA_SOMBRA'][d] += 1
        elif tipo == 'CORTINAS_LATERALES':
            conteo['CORTINAS_LATERALES'][d] += 1
        elif tipo == 'VENTILACION' and ev.a_que_estado_paso == 'ENCENDIDO':
            conteo['VENTILACION'][d] += 1
    return conteo


def generar_reporte_csv(
    id_invernadero: int,
    fecha_desde: date,
    fecha_hasta: date,
    fecha_generacion: datetime,
    tipo: str = 'HISTORICO_CONSOLIDADO',
) -> Reporte:
    """Genera un archivo CSV real en REPORTES_DIR con base en el rango de fechas solicitado."""
    reportes_dir = Path(settings.REPORTES_DIR)
    reportes_dir.mkdir(parents=True, exist_ok=True)

    dt_inicio = datetime.combine(fecha_desde, time.min)
    dt_fin = datetime.combine(fecha_hasta, time.max)

    temps = list(
        HistorialTemperatura.objects.filter(
            invernadero_id=id_invernadero,
            fecha__range=(dt_inicio, dt_fin),
        ).order_by('fecha')
    )
    rads = list(
        HistorialRadiacion.objects.filter(
            invernadero_id=id_invernadero,
            fecha__range=(dt_inicio, dt_fin),
        ).order_by('fecha')
    )
    vientos = list(
        HistorialViento.objects.filter(
            invernadero_id=id_invernadero,
            fecha__range=(dt_inicio, dt_fin),
        ).order_by('fecha')
    )
    climas = list(
        HistorialClima.objects.filter(
            invernadero_id=id_invernadero,
            es_pronostico=False,
            fecha__range=(dt_inicio, dt_fin),
        ).order_by('fecha')
    )
    mecanismos_ev = list(
        HistorialMecanismo.objects.select_related('mecanismo')
        .filter(mecanismo__invernadero_id=id_invernadero, fecha__range=(dt_inicio, dt_fin))
        .order_by('fecha')
    )
    alertas = list(
        Alerta.objects.filter(
            invernadero_id=id_invernadero,
            fecha__range=(dt_inicio, dt_fin),
        ).order_by('fecha')
    )

    despliegues = _contar_despliegues_diarios(mecanismos_ev)

    temps_dia: dict[date, list[float]] = defaultdict(list)
    for t in temps:
        temps_dia[t.fecha.date()].append(t.grados)

    rads_dia: dict[date, list[float]] = defaultdict(list)
    for r in rads:
        rads_dia[r.fecha.date()].append(r.valor)

    vientos_dia: dict[date, list[float]] = defaultdict(list)
    for v in vientos:
        vientos_dia[v.fecha.date()].append(v.valor)

    climas_dia: dict[date, list[str]] = defaultdict(list)
    for c in climas:
        nombre_c = ETIQUETAS_CLIMA.get(c.estado, c.estado)
        if nombre_c not in climas_dia[c.fecha.date()]:
            climas_dia[c.fecha.date()].append(nombre_c)

    alertas_dia: dict[date, list[Alerta]] = defaultdict(list)
    for a in alertas:
        alertas_dia[a.fecha.date()].append(a)

    marca = fecha_generacion.strftime('%Y%m%d_%H%M%S')
    prefijo = 'Historico_Invernadero' if tipo == 'HISTORICO_CONSOLIDADO' else 'Detalle_Eventos'
    nombre_archivo = f'{prefijo}_{fecha_desde:%Y%m%d}_a_{fecha_hasta:%Y%m%d}_{marca}.csv'
    ruta_completa = reportes_dir / nombre_archivo

    filas_escritas = 0
    with open(ruta_completa, 'w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        if tipo == 'HISTORICO_CONSOLIDADO':
            writer.writerow([
                'Fecha',
                'Temporada',
                'Temp_Min_C',
                'Temp_Promedio_C',
                'Temp_Max_C',
                'Radiacion_Promedio_Wm2',
                'Radiacion_Max_Wm2',
                'Viento_Promedio_kmh',
                'Viento_Max_kmh',
                'Despliegues_Media_Sombra',
                'Despliegues_Cortinas_Laterales',
                'Activaciones_Ventilacion',
                'Condiciones_Climaticas',
                'Cantidad_Alertas',
                'Resumen_Eventos',
            ])
            dias = sorted(
                set(temps_dia) | set(rads_dia) | set(vientos_dia) | set(climas_dia) | set(alertas_dia)
                | set(despliegues['MEDIA_SOMBRA']) | set(despliegues['CORTINAS_LATERALES'])
            )
            if not dias:
                dia_cursor = fecha_desde
                while dia_cursor <= fecha_hasta:
                    dias.append(dia_cursor)
                    dia_cursor += timedelta(days=1)

            for d in dias:
                ts = temps_dia.get(d, [])
                rs = rads_dia.get(d, [])
                vs = vientos_dia.get(d, [])
                cs = climas_dia.get(d, [])
                als = alertas_dia.get(d, [])
                resumen = ' | '.join(
                    f"[{a.fecha:%H:%M}] {a.titulo or a.variable}: {a.descripcion}"
                    for a in als[:5]
                ) or 'Operación dentro de parámetros'
                writer.writerow([
                    d.isoformat(),
                    obtener_temporada(d),
                    f'{min(ts):.1f}' if ts else 'N/D',
                    f'{(sum(ts) / len(ts)):.1f}' if ts else 'N/D',
                    f'{max(ts):.1f}' if ts else 'N/D',
                    f'{(sum(rs) / len(rs)):.0f}' if rs else 'N/D',
                    f'{max(rs):.0f}' if rs else 'N/D',
                    f'{(sum(vs) / len(vs)):.1f}' if vs else 'N/D',
                    f'{max(vs):.1f}' if vs else 'N/D',
                    despliegues['MEDIA_SOMBRA'].get(d, 0),
                    despliegues['CORTINAS_LATERALES'].get(d, 0),
                    despliegues['VENTILACION'].get(d, 0),
                    '; '.join(cs) if cs else 'Sin cambios registrados',
                    len(als),
                    resumen,
                ])
                filas_escritas += 1
        else:
            writer.writerow([
                'Fecha',
                'Hora',
                'Temporada',
                'Categoria',
                'Temperatura_C',
                'Radiacion_Wm2',
                'Viento_kmh',
                'Despliegues_Media_Sombra_Dia',
                'Despliegues_Cortinas_Laterales_Dia',
                'Condiciones_Climaticas_Dia',
                'Detalle',
            ])
            eventos_crono: list[tuple[datetime, str, str, str, str, str, str]] = []
            rad_por_ts = {r.fecha: r.valor for r in rads}
            viento_por_ts = {v.fecha: v.valor for v in vientos}
            for t in temps:
                r_val = rad_por_ts.get(t.fecha)
                v_val = viento_por_ts.get(t.fecha)
                eventos_crono.append((
                    t.fecha,
                    'MEDICION',
                    f'{t.grados:.1f}',
                    f'{r_val:.0f}' if r_val is not None else '',
                    f'{v_val:.1f}' if v_val is not None else '',
                    'Lectura de sensores',
                    '',
                ))
            for c in climas:
                eventos_crono.append((
                    c.fecha,
                    'CLIMA',
                    f'{c.temp_externa:.1f}' if c.temp_externa is not None else '',
                    '',
                    f'{c.viento_estimado:.1f}' if c.viento_estimado is not None else '',
                    f'Condición climática: {ETIQUETAS_CLIMA.get(c.estado, c.estado)}',
                    '',
                ))
            for ev in mecanismos_ev:
                eventos_crono.append((
                    ev.fecha,
                    f'MECANISMO ({ev.origen})',
                    '',
                    '',
                    '',
                    f'{ev.mecanismo.get_tipo_display()} -> {ev.a_que_estado_paso}',
                    '',
                ))
            for a in alertas:
                eventos_crono.append((
                    a.fecha,
                    f'{a.categoria} ({a.nivel})',
                    f'{a.valor_detectado:.1f}' if a.variable == 'TEMPERATURA' else '',
                    f'{a.valor_detectado:.0f}' if a.variable == 'RADIACION' else '',
                    f'{a.valor_detectado:.1f}' if a.variable == 'VIENTO' else '',
                    f'{a.titulo}: {a.descripcion}' if a.titulo else a.descripcion,
                    '',
                ))
            eventos_crono.sort(key=lambda x: x[0])
            for ts, cat, t_str, r_str, v_str, det, _ in eventos_crono:
                d = ts.date()
                writer.writerow([
                    d.isoformat(),
                    ts.strftime('%H:%M:%S'),
                    obtener_temporada(d),
                    cat,
                    t_str,
                    r_str,
                    v_str,
                    despliegues['MEDIA_SOMBRA'].get(d, 0),
                    despliegues['CORTINAS_LATERALES'].get(d, 0),
                    '; '.join(climas_dia.get(d, [])) or 'Normal',
                    det,
                ])
                filas_escritas += 1

    return Reporte.objects.create(
        invernadero_id=id_invernadero,
        nombre=nombre_archivo,
        tipo=tipo,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        fecha_generacion=fecha_generacion,
        ruta_archivo=str(ruta_completa),
        filas=filas_escritas,
    )


def eliminar_reporte(reporte_id: int) -> bool:
    rep = Reporte.objects.filter(id=reporte_id).first()
    if rep is None:
        return False
    reportes_dir = Path(settings.REPORTES_DIR).resolve()
    ruta = Path(rep.ruta_archivo).resolve()
    try:
        if ruta.exists() and (reportes_dir == ruta.parent or reportes_dir in ruta.parents):
            ruta.unlink()
    except OSError:
        pass
    rep.delete()
    return True
