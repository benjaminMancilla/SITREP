from django.urls import path
from django.http import HttpResponse
from . import views

app_name = 'inventory'


def revocar_dispositivo_placeholder(request, slug, id):
    return HttpResponse(
        f"Revocacion placeholder para dispositivo {id} en {slug}.",
        status=200,
    )


urlpatterns = [
    path('login/', views.login_tierra, name='login_tierra'),
    path('kiosco/login/', views.login_kiosco, name='login_kiosco'),
    path('', views.tenant_home_placeholder, name='tenant_home'),
    path('kiosco/', views.kiosco_home_placeholder, name='kiosco_home'),
    path('kiosco/hardware/setup/', views.setup_kiosco, name='setup_kiosco'),
    path(
        'kiosco/hardware/<int:id>/revocar/',
        revocar_dispositivo_placeholder,
        name='revocar_dispositivo',
    ),
]
