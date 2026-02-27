from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Nave
from .services import MotorReglasSITREP

@receiver(post_save, sender=Nave)
def trigger_sincronizacion_matriz(sender, instance, created, **kwargs):
    """
    Escucha cada vez que se guarda una Nave. Si está activa, corre el motor de reglas.
    """
    if instance.is_active:
        MotorReglasSITREP.sincronizar_matriz_nave(instance)