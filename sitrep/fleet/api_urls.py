from django.urls import path

from . import api_views

urlpatterns = [
    path('dispositivos/verificar/', api_views.VerificarDispositivoView.as_view(), name='verificar_dispositivo'),
    path('naves/', api_views.NavesEstadoView.as_view(), name='api_naves_estado'),
    path('naves/actividad/', api_views.FleetActividadView.as_view(), name='fleet_actividad'),
]
