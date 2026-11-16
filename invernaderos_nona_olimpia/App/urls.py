from django.urls import path
from . import views

urlpatterns = [
    path('', views.monitor_view, name='monitor'),
    path('historial/', views.historial_view, name='historial'),
    path('alertas/', views.alertas_view, name='alertas'),
    path('reportes/', views.reportes_view, name='reportes'),
    path('configuracion/', views.configuracion_view, name='configuracion'),
    path('acerca-de/', views.acerca_de_view, name='acerca_de'),
]
