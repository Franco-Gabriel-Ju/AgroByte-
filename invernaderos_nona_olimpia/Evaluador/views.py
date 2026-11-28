from django.http import JsonResponse

from App.models import Alerta, Invernadero
from Simulador.views import get_simulator

from .evaluador import obtener_evaluador


def api_estado(request):
    """Retorna el estado del Evaluador, temporizadores de persistencia y alertas recientes."""
    sim = get_simulator()
    instante = sim.instante
    ev = obtener_evaluador()
    resumen = ev.estado_resumen(instante)

    inv = Invernadero.objects.first()
    alertas_qs = Alerta.objects.filter(invernadero=inv).order_by('-fecha')[:15] if inv else []
    alertas = [
        {
            'id': a.id,
            'hora': a.fecha.strftime('%H:%M:%S'),
            'fecha': a.fecha.strftime('%Y-%m-%d %H:%M:%S'),
            'categoria': a.categoria,
            'nivel': a.nivel,
            'variable': a.variable,
            'valor_detectado': a.valor_detectado,
            'umbral': a.umbral,
            'titulo': a.titulo,
            'descripcion': a.descripcion,
            'resuelta': a.resuelta,
        }
        for a in alertas_qs
    ]

    return JsonResponse({
        'ok': True,
        'instante_simulado': instante.isoformat(),
        'hora_simulada': instante.strftime('%H:%M:%S'),
        **resumen,
        'alertas_recientes': alertas,
    })
