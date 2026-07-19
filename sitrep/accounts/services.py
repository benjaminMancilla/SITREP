import logging
import smtplib

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Q
from django.http import Http404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from core.permissions import ROLES_TIERRA
from core.services import enviar_email
from core.utils import get_client_ip
from sitrep.accounts.models import AuditEvent
from sitrep.fleet.models import Tripulacion
from sitrep.fleet.services import FleetQueryService

logger = logging.getLogger(__name__)

Usuario = get_user_model()


def solicitar_recuperacion(request, email):
    """Manda el correo de reset si el email corresponde a una cuenta de tierra
    del tenant. Silencioso a propósito (anti-enumeración): el llamador nunca sabe
    si hubo match, y un fallo de SMTP no se propaga.

    Token: default_token_generator de Django (firmado, vence según
    PASSWORD_RESET_TIMEOUT, y de un solo uso porque embebe el hash de la
    contraseña). Sin tabla propia.
    """
    naviera = getattr(request, "naviera", None)
    usuario = Usuario.objects.filter(
        naviera=naviera, email__iexact=email, is_active=True, rol__in=ROLES_TIERRA
    ).first()
    if usuario is None or not usuario.has_usable_password():
        return

    uidb64 = urlsafe_base64_encode(force_bytes(usuario.pk))
    token = default_token_generator.make_token(usuario)
    reset_url = request.build_absolute_uri(
        reverse(
            "inventory:confirmar_recuperacion",
            kwargs={"slug": naviera.slug, "uidb64": uidb64, "token": token},
        )
    )
    contexto = {"usuario": usuario, "naviera": naviera, "reset_url": reset_url}
    html = render_to_string("emails/password_reset.html", contexto)
    texto = (
        "Recibimos una solicitud para restablecer tu contraseña en SITREP.\n\n"
        f"Abre este enlace para elegir una nueva:\n{reset_url}\n\n"
        "El enlace vence en 72 horas. Si no fuiste tú, ignora este correo."
    )
    try:
        enviar_email([usuario.email], "Restablece tu contraseña de SITREP", texto, html_body=html)
    except (smtplib.SMTPException, OSError):
        logger.exception("Fallo al enviar correo de recuperación de contraseña")


def resolver_usuario_reset(request, uidb64, token):
    """Usuario válido para este enlace de reset, o None. Scoped al tenant y a
    roles de tierra; el token debe seguir vigente."""
    naviera = getattr(request, "naviera", None)
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        usuario = Usuario.objects.get(
            pk=uid, naviera=naviera, is_active=True, rol__in=ROLES_TIERRA
        )
    except (TypeError, ValueError, OverflowError, Usuario.DoesNotExist):
        return None
    if not default_token_generator.check_token(usuario, token):
        return None
    return usuario


def notificar_ayuda_pin(request, rut, dispositivo_token):
    """Avisa por correo a quienes pueden resetear el PIN (capitán de la nave del
    kiosco + admins de la naviera) que este rut pidió ayuda, con un enlace directo
    a cambiar_pin.

    El pedido SOLO se procesa si viene de un kiosco autorizado y activo de la
    naviera y el rut es tripulante de la nave de ese kiosco. Así, la única forma de
    gatillar el aviso es teniendo acceso físico a un kiosco válido y sabiendo el rut
    de un tripulante real de esa nave — no se puede pedir desde un navegador
    cualquiera. Silencioso ante cualquier fallo de validación o de SMTP.
    """
    naviera = getattr(request, "naviera", None)
    dispositivo = FleetQueryService.buscar_dispositivo_por_token(
        getattr(naviera, "id", None), dispositivo_token
    )
    if dispositivo is None or not dispositivo.is_active:
        return

    solicitante = Usuario.objects.filter(
        naviera=naviera, rut=rut, is_active=True, rol="mar"
    ).first()
    if solicitante is None:
        return
    if not Tripulacion.objects.filter(usuario=solicitante, nave=dispositivo.nave).exists():
        return

    # Pedido legítimo: dejar rastro y avisar a quienes pueden resetear.
    AuditEvent.objects.create(
        naviera=naviera,
        accion="write",
        recurso="solicitud_pin",
        detalle=rut,
        ip=get_client_ip(request),
        endpoint=request.path,
    )
    correos = list(
        Usuario.objects.filter(naviera=naviera, is_active=True)
        .filter(
            Q(rol="admin_naviera")
            | Q(rol="capitan", asignaciones_naves__nave=dispositivo.nave)
        )
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
        .distinct()
    )
    if not correos:
        return

    reset_url = request.build_absolute_uri(
        reverse("inventory:cambiar_pin", kwargs={"slug": naviera.slug, "id": solicitante.id})
    )
    contexto = {"solicitante": solicitante, "naviera": naviera, "reset_url": reset_url}
    html = render_to_string("emails/pin_reset_request.html", contexto)
    texto = (
        f"El tripulante {solicitante.rut} solicitó ayuda para restablecer su PIN de kiosco.\n\n"
        "IMPORTANTE: verifica que la solicitud sea real antes de restablecer el PIN. "
        "Confirma la identidad del tripulante en persona o por un canal de confianza; "
        "el pedido salió de un kiosco autorizado, pero eso no prueba quién lo envió.\n\n"
        f"Puedes resetearlo aquí:\n{reset_url}"
    )
    try:
        # Individual para no exponer los correos del resto de destinatarios entre sí.
        for correo in correos:
            enviar_email([correo], "Solicitud de restablecimiento de PIN — SITREP", texto, html_body=html)
    except (smtplib.SMTPException, OSError):
        logger.exception("Fallo al enviar aviso de ayuda de PIN")


class AccountsQueryService:
    @staticmethod
    def _get_or_404(model, **kwargs):
        try:
            return model.objects.get(**kwargs)
        except model.DoesNotExist as exc:
            raise Http404("Recurso no encontrado.") from exc

    @staticmethod
    def get_usuario_del_tenant(naviera, usuario_id):
        return AccountsQueryService._get_or_404(Usuario, id=usuario_id, naviera=naviera)

    @staticmethod
    def get_usuario_activo_del_tenant(naviera, usuario_id):
        return AccountsQueryService._get_or_404(Usuario, id=usuario_id, naviera=naviera, is_active=True)

    @staticmethod
    def get_usuarios_del_tenant(naviera):
        return Usuario.objects.filter(naviera=naviera, is_active=True, is_superuser=False)
