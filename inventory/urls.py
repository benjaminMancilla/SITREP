from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    # URL restringida para configuración de tablets
    path('hardware/setup/', views.setup_kiosco, name='setup_kiosco'),
]