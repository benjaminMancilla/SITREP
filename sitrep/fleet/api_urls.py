from django.urls import path

from . import api_views

urlpatterns = [
    path('dispositivos/verificar/', api_views.VerificarDispositivoView.as_view(), name='verificar_dispositivo'),
]
