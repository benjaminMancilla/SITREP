from django.urls import path

from . import api_views

urlpatterns = [
    path("dashboard/urgencia/", api_views.UrgenciaPorPeriodicidadView.as_view(), name="api_urgencia"),
]
