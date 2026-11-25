from django.contrib import admin
from .models import (
    Cultivo, Parametro, HistorialParametro, Invernadero,
    HistorialTemperatura, HistorialRadiacion, HistorialViento,
    HistorialClima, Mecanismo, HistorialMecanismo, Alerta,
    Usuario, Reporte
)

admin.site.register([
    Cultivo, Parametro, HistorialParametro, Invernadero,
    HistorialTemperatura, HistorialRadiacion, HistorialViento,
    HistorialClima, Mecanismo, HistorialMecanismo, Alerta,
    Usuario, Reporte
])
