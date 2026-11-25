from django.urls import path
from . import views

app_name = 'simulador'

urlpatterns = [
    path('', views.simulador_index, name='index'),
    path('api/estado/', views.api_estado, name='api_estado'),
    path('api/actuador/', views.api_actuador, name='api_actuador'),
    path('api/clima/', views.api_clima, name='api_clima'),
    path('api/viento/', views.api_viento, name='api_viento'),
    path('api/modo/', views.api_modo, name='api_modo'),
    path('api/velocidad/', views.api_velocidad, name='api_velocidad'),
    path('api/reset/', views.api_reset, name='api_reset'),
]
