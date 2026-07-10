from django.urls import path

from . import views

urlpatterns = [
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

    # Hardware kiosco
    path('kiosco/hardware/', views.listar_dispositivos, name='listar_dispositivos'),
    path('kiosco/hardware/setup/', views.setup_kiosco, name='setup_kiosco'),
    path(
        'kiosco/hardware/<int:id>/revocar/',
        views.revocar_dispositivo,
        name='revocar_dispositivo',
    ),
]
