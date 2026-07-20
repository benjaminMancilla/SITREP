from django.urls import path

from . import views

urlpatterns = [
    path('login/', views.login_unificado, {'modo_default': 'tierra'}, name='login_tierra'),
    path('logout/', views.logout_tierra, name='logout_tierra'),
    path('kiosco/login/', views.redirect_kiosco_login, name='login_kiosco'),
    path('kiosco/logout/', views.logout_kiosco, name='logout_kiosco'),
    path('recuperar/', views.solicitar_recuperacion_password, name='recuperar_password'),
    path('recuperar/confirmar/<uidb64>/<token>/', views.confirmar_recuperacion_password, name='confirmar_recuperacion'),
    path('ayuda-pin/', views.solicitar_ayuda_pin, name='solicitar_ayuda_pin'),

    # Usuarios
    path('usuarios/', views.listar_usuarios, name='listar_usuarios'),
    path('usuarios/crear/', views.crear_usuario, name='crear_usuario'),
    path('usuarios/<int:id>/desactivar/', views.desactivar_usuario, name='desactivar_usuario'),
    path('usuarios/<int:id>/pin/', views.cambiar_pin, name='cambiar_pin'),
]
