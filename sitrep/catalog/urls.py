from django.urls import path

from . import views

urlpatterns = [
    path("catalogo/", views.catalogo_admin, name="catalogo_admin"),
]
