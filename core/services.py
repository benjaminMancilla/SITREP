import logging

logger = logging.getLogger(__name__)


def enviar_email_contacto(nombre, email, naviera, mensaje):
    # placeholder hasta que exista un servicio de mail reutilizable.
    # Reemplazar este log por el envío real (ver servicio de mail pendiente).
    logger.info(
        "Nuevo contacto desde landing: nombre=%s email=%s naviera=%s mensaje=%s",
        nombre, email, naviera, mensaje,
    )
