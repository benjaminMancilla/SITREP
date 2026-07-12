from django.urls import path

from . import api_views

urlpatterns = [
    path("catalogo/efectivo/", api_views.CatalogoEfectivoView.as_view(), name="api_catalogo_efectivo"),
    path("catalogo/recursos/", api_views.RecursoPublicarView.as_view(), name="api_catalogo_recursos"),
    path("catalogo/independiente/", api_views.CatalogoIndependienteView.as_view(), name="api_catalogo_independiente"),
    path("catalogo/revertir/", api_views.CatalogoRevertirView.as_view(), name="api_catalogo_revertir"),
]
