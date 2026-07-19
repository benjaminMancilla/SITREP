import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def enviar_email(to, subject, body, from_email=None, html_body=None):
    """Envío genérico, reutilizable por cualquier flujo (reset de password, notificaciones, etc).

    from_email por defecto es el no-reply; los flujos que necesitan otro remitente
    (ej. contacto) lo pasan explícito. body es el texto plano (fallback); html_body,
    si viene, va como alternativa HTML en el mismo correo.
    """
    send_mail(subject, body, from_email or settings.DEFAULT_FROM_EMAIL, to, html_message=html_body)


def _armar_cuerpo_formulario(nombre, email, empresa, mensaje, extra_lines=""):
    return (
        f"Nombre: {nombre}\n"
        f"Email: {email}\n"
        f"Empresa: {empresa or '-'}\n"
        f"{extra_lines}"
        f"\nMensaje:\n{mensaje}"
    )


def enviar_email_contacto(nombre, email, naviera, mensaje):
    subject = f"Nuevo contacto desde la landing: {nombre}"
    body = _armar_cuerpo_formulario(nombre, email, naviera, mensaje)
    enviar_email([settings.CONTACT_EMAIL_TO], subject, body, from_email=settings.CONTACT_EMAIL_TO)


def enviar_email_arco(nombre, rut, email, empresa, mensaje):
    subject = f"Solicitud ARCO: {nombre}"
    body = _armar_cuerpo_formulario(nombre, email, empresa, mensaje, extra_lines=f"RUT: {rut}\n")
    enviar_email([settings.ARCO_EMAIL_TO], subject, body, from_email=settings.ARCO_EMAIL_TO)
