import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def enviar_email(to, subject, body, from_email=None):
    """Envío genérico, reutilizable por cualquier flujo (reset de password, notificaciones, etc).

    from_email por defecto es el no-reply; los flujos que necesitan otro remitente
    (ej. contacto) lo pasan explícito.
    """
    send_mail(subject, body, from_email or settings.DEFAULT_FROM_EMAIL, to)


def enviar_email_contacto(nombre, email, naviera, mensaje):
    subject = f"Nuevo contacto desde la landing: {nombre}"
    body = (
        f"Nombre: {nombre}\n"
        f"Email: {email}\n"
        f"Naviera/empresa: {naviera or '-'}\n\n"
        f"Mensaje:\n{mensaje}"
    )
    enviar_email([settings.CONTACT_EMAIL_TO], subject, body, from_email=settings.CONTACT_EMAIL_TO)
