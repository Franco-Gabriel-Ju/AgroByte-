from django.shortcuts import render

def monitor_view(request):
    """Página principal de monitoreo en tiempo real del invernadero (Index)."""
    return render(request, 'pages/monitor.html')

def historial_view(request):
    """Página de pronóstico y gráficos históricos de clima y radiación."""
    return render(request, 'pages/historial.html')

def alertas_view(request):
    """Página de historial de alertas, recomendaciones y activaciones."""
    return render(request, 'pages/alertas.html')

def reportes_view(request):
    """Página de generación y visualización de reportes."""
    return render(request, 'pages/reportes.html')

def configuracion_view(request):
    """Página de configuración de umbrales y parámetros del sistema."""
    return render(request, 'pages/configuracion.html')

def acerca_de_view(request):
    """Página informativa sobre el sistema AgroByte - Invernaderos Nona Olimpia."""
    return render(request, 'pages/acerca_de.html')
