from django.urls import path
from . import views

app_name = 'evaluador'

urlpatterns = [
    path('api/estado/', views.api_estado, name='api_estado'),
]
