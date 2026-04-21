from django.urls import path
from . import views

app_name = 'inventory'


urlpatterns = [
    path('login/', views.login_tierra, name='login_tierra'),
    path('logout/', views.logout_tierra, name='logout_tierra'),
    path('kiosco/login/', views.login_kiosco, name='login_kiosco'),
    path('kiosco/logout/', views.logout_kiosco, name='logout_kiosco'),
    path('', views.dashboard_tierra, name='tenant_home'),
    path('kiosco/', views.dashboard_kiosco, name='kiosco_home'),
    # Usuarios
    path('usuarios/', views.listar_usuarios, name='listar_usuarios'),
    path('usuarios/crear/', views.crear_usuario, name='crear_usuario'),
    path('usuarios/<int:id>/desactivar/', views.desactivar_usuario, name='desactivar_usuario'),
    path('usuarios/<int:id>/pin/', views.cambiar_pin, name='cambiar_pin'),

    # Naves
    path('naves/', views.listar_naves, name='listar_naves'),
    path('naves/crear/', views.crear_nave, name='crear_nave'),
    path('naves/<int:nave_id>/editar/', views.editar_nave, name='editar_nave'),
    path('naves/<int:nave_id>/desactivar/', views.desactivar_nave, name='desactivar_nave'),

    # Tripulación
    path('naves/<int:nave_id>/tripulacion/', views.listar_tripulacion, name='listar_tripulacion'),
    path('naves/<int:nave_id>/tripulacion/agregar/', views.agregar_tripulante, name='agregar_tripulante'),
    path(
        'naves/<int:nave_id>/tripulacion/<int:tripulacion_id>/remover/',
        views.remover_tripulante,
        name='remover_tripulante',
    ),

    # API JSON — Kiosco
    path('api/periodos/', views.api_periodos_nave, name='api_periodos_nave'),
    path('api/periodos/<int:periodo_id>/recursos/', views.api_recursos_periodo, name='api_recursos_periodo'),
    path(
        'api/periodos/<int:periodo_id>/recursos/<int:recurso_id>/',
        views.api_detalle_recurso,
        name='api_detalle_recurso',
    ),
    path(
        'api/periodos/<int:periodo_id>/recursos/<int:recurso_id>/ficha/',
        views.api_crear_ficha,
        name='api_crear_ficha',
    ),
    path(
        'api/periodos/<int:periodo_id>/recursos/<int:recurso_id>/ficha/modificar/',
        views.api_modificar_ficha,
        name='api_modificar_ficha',
    ),

    path('kiosco/hardware/', views.listar_dispositivos, name='listar_dispositivos'),
    path('kiosco/hardware/setup/', views.setup_kiosco, name='setup_kiosco'),
    path(
        'kiosco/hardware/<int:id>/revocar/',
        views.revocar_dispositivo,
        name='revocar_dispositivo',
    ),
]
