from django.urls import include, path
from . import views

app_name = 'inventory'


urlpatterns = [
    path('', include('sitrep.accounts.urls')),
    path('', include('sitrep.fleet.urls')),
    path('', include('sitrep.catalog.urls')),

    path('', views.dashboard_tierra, name='tenant_home'),
    path('fallos/', views.fallos_activos, name='fallos_activos'),
    path('fallos/resueltos/', views.fallos_resueltos, name='fallos_resueltos'),
    path('fallos/feed/', views.fallos_feed, name='fallos_feed'),
    path('vencidos/', views.periodos_vencidos, name='periodos_vencidos'),
    path('naves/<int:nave_id>/detalle/', views.nave_detalle, name='nave_detalle'),
    path(
        'naves/<int:nave_id>/periodos/<int:periodo_id>/pdf/',
        views.nave_periodo_pdf,
        name='nave_periodo_pdf',
    ),

    path('kiosco/', views.dashboard_kiosco, name='kiosco_home'),
    path('kiosco/periodos/<int:periodo_id>/', views.kiosco_periodo_detalle, name='kiosco_periodo_detalle'),
    path(
        'kiosco/periodos/<int:periodo_id>/pdf/',
        views.kiosco_periodo_pdf,
        name='kiosco_periodo_pdf',
    ),
    path(
        'kiosco/periodos/<int:periodo_id>/historial/',
        views.kiosco_periodo_historial,
        name='kiosco_periodo_historial',
    ),
    path(
        'kiosco/periodos/<int:periodo_id>/recursos/<int:recurso_id>/ficha/',
        views.kiosco_recurso_ficha,
        name='kiosco_recurso_ficha',
    ),

    path('api/v1/', include('core.api_urls')),

    # API JSON — Kiosco
    path(
        'api/periodos/<int:periodo_id>/fichas/bulk/',
        views.api_guardar_fichas_periodo,
        name='api_guardar_fichas_periodo',
    ),
]
