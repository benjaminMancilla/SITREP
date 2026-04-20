import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Nave
from .services import MotorPeriodos, MotorReglasSITREP

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Nave)
def trigger_sincronizacion(sender, instance, created, **kwargs):
    """
    Escucha cada vez que se guarda una Nave.
    - Si está activa: sincroniza la MatrizNaveRecurso.
    - Si además es nueva (created): inicializa sus PeriodoRevision.
    Cada motor tiene su propio try/except — un fallo no cancela el otro.
    """
    if instance.is_active:
        try:
            MotorReglasSITREP.sincronizar_matriz_nave(instance)
        except Exception:
            logger.error(
                f"Error sincronizando matriz nave {instance.id}",
                exc_info=True,
            )

        if created:
            try:
                MotorPeriodos.sincronizar_periodos_nave(instance)
            except Exception:
                logger.error(
                    f"Error inicializando periodos nave {instance.id}",
                    exc_info=True,
                )