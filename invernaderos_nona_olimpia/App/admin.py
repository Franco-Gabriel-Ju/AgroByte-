from django.contrib import admin
from .models import (
    Cultivo, Parametro, HistorialParametro, Invernadero,
    HistorialTemperatura, HistorialRadiacion, HistorialClima,
    Mecanismo, HistorialMecanismo, Alerta
)

admin.site.register([
    Cultivo, Parametro, HistorialParametro, Invernadero,
    HistorialTemperatura, HistorialRadiacion, HistorialClima,
    Mecanismo, HistorialMecanismo, Alerta
])