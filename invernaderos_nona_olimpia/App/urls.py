from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    path('', views.monitor_view, name='monitor'),
    path('historial/', views.historial_view, name='historial'),
    path('alertas/', views.alertas_view, name='alertas'),
    path('reportes/', views.reportes_view, name='reportes'),
    path('configuracion/', views.configuracion_view, name='configuracion'),
    path('acerca-de/', views.acerca_de_view, name='acerca_de'),

    path('api/monitor/', views.api_monitor, name='api_monitor'),
    path('api/modo/', views.api_modo, name='api_modo'),
    path('api/mecanismo/', views.api_mecanismo, name='api_mecanismo'),
    path('api/alertas/leer/', views.api_alertas_leer, name='api_alertas_leer'),
    path('api/historial/', views.api_historial, name='api_historial'),
    path('api/alertas/', views.api_alertas, name='api_alertas'),
    path('api/configuracion/', views.api_configuracion, name='api_configuracion'),
    path('api/cultivos/', views.api_cultivos, name='api_cultivos'),
    path('api/reportes/', views.api_reportes, name='api_reportes'),
    path('api/reportes/generar/', views.api_generar_reporte, name='api_generar_reporte'),
    path('reportes/<int:reporte_id>/descargar/', views.descargar_reporte, name='descargar_reporte'),
    path('api/reportes/<int:reporte_id>/eliminar/', views.api_eliminar_reporte, name='api_eliminar_reporte'),
]
