from django.urls import path

from . import api_views

urlpatterns = [
    path("dashboard/urgencia/", api_views.UrgenciaPorPeriodicidadView.as_view(), name="api_urgencia"),
    path("fallos/feed/", api_views.FallosFeedView.as_view(), name="api_fallos_feed"),
    path("hitos/inminentes/", api_views.HitosInminentesView.as_view(), name="api_hitos_inminentes"),
]
