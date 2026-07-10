import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from sitrep.fleet.models import Nave
from .services import MotorPeriodos

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Nave)
def trigger_sincronizacion(sender, instance, created, **kwargs):
    """
    Al crear una nave activa, inicializa su MatrizNaveRecurso y sus
    PeriodoRevision. Ediciones posteriores (ej. desde admin) NO resincronizan:
    la ficha abierta de un período apunta a una versión fija del catálogo, y
    resincronizar en cada guardado la rompería. La sync solo vuelve a ocurrir
    en cambio de período (MotorPeriodos) o de forma explícita (acción de
    admin / management command sincronizar_matriz).
    """
    if created and instance.is_active:
        try:
            MotorPeriodos.sincronizar_periodos_nave(instance)
        except Exception:
            logger.error(
                f"Error inicializando periodos nave {instance.id}",
                exc_info=True,
            )