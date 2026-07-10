import logging
import smtplib

from django.contrib import messages
from django.shortcuts import redirect, render
from django.http import HttpResponse, JsonResponse, QueryDict
from django.db import connection
from django.urls import reverse
from django.views.decorators.cache import never_cache

from django.conf import settings

from core.forms import ContactoForm, ArcoForm
from core.services import enviar_email_contacto, enviar_email_arco
from core.utils import get_client_ip, throttle, verify_turnstile
from sitrep.accounts.models import Naviera

logger = logging.getLogger(__name__)

CONTACTO_SESSION_KEY = "contacto_form_data"
ARCO_SESSION_KEY = "arco_form_data"
LEGAL_PAGE_URL_NAMES = {
    "terminos": "legal_terminos",
    "privacidad": "legal_privacidad",
    "dpa": "legal_dpa",
}


def homepage(request):
    navieras = Naviera.objects.filter(slug__isnull=False).order_by("nombre")
    stashed = request.session.pop(CONTACTO_SESSION_KEY, None)
    contacto_form = ContactoForm(QueryDict(stashed)) if stashed else ContactoForm()
    return render(request, "homepage.html", {
        "navieras": navieras,
        "contacto_form": contacto_form,
        "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
    })


@throttle("contacto", limit=3, window_seconds=600)
def contacto(request):
    if request.method != "POST":
        return redirect("homepage")

    form = ContactoForm(request.POST)
    # Se guarda para que homepage() pueda re-mostrar los valores tras el
    # redirect (PRG: evita reenvío del form al recargar la página).
    request.session[CONTACTO_SESSION_KEY] = request.POST.urlencode()

    if not form.is_valid():
        messages.error(request, "Revisa los datos del formulario e inténtalo de nuevo.")
        return redirect(f"{reverse('homepage')}#contacto")

    if form.is_spam():
        # No delatar al bot: mismo mensaje de éxito, pero sin gastar crédito de Resend.
        logger.info("Contacto descartado por honeypot")
        messages.success(request, "Gracias, te contactaremos a la brevedad.")
        return redirect(f"{reverse('homepage')}#contacto")

    token = request.POST.get("cf-turnstile-response")
    if not verify_turnstile(token, get_client_ip(request)):
        messages.error(request, "No pudimos verificar que no eres un robot, intenta de nuevo.")
        return redirect(f"{reverse('homepage')}#contacto")

    datos = {k: v for k, v in form.cleaned_data.items() if k != "pagina_web"}
    try:
        enviar_email_contacto(**datos)
    except (smtplib.SMTPException, OSError):
        logger.exception("Fallo al enviar el correo de contacto")
        messages.error(request, "No pudimos enviar tu mensaje, intenta nuevamente en unos minutos.")
        return redirect(f"{reverse('homepage')}#contacto")

    messages.success(request, "Gracias, te contactaremos a la brevedad.")
    return redirect(f"{reverse('homepage')}#contacto")


def _legal_page(request, template_name, slug):
    stashed = request.session.pop(ARCO_SESSION_KEY, None)
    arco_form = ArcoForm(QueryDict(stashed)) if stashed else ArcoForm()
    return render(request, template_name, {
        "arco_form": arco_form,
        "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
        "legal_page_slug": slug,
    })


def legal_terminos(request):
    return _legal_page(request, "legal/terminos.html", "terminos")


def legal_privacidad(request):
    return _legal_page(request, "legal/privacidad.html", "privacidad")


def legal_dpa(request):
    return _legal_page(request, "legal/dpa.html", "dpa")


@throttle("arco", limit=3, window_seconds=600)
def arco_solicitud(request):
    if request.method != "POST":
        return redirect("legal_privacidad")

    url_name = LEGAL_PAGE_URL_NAMES.get(request.POST.get("pagina"), "legal_privacidad")
    redirect_url = f"{reverse(url_name)}#arco"

    form = ArcoForm(request.POST)
    # Se guarda para que _legal_page() pueda re-mostrar los valores tras el
    # redirect (PRG: evita reenvío del form al recargar la página).
    request.session[ARCO_SESSION_KEY] = request.POST.urlencode()

    if not form.is_valid():
        messages.error(request, "Revisa los datos del formulario e inténtalo de nuevo.")
        return redirect(redirect_url)

    if form.is_spam():
        # No delatar al bot: mismo mensaje de éxito, pero sin gastar crédito de Resend.
        logger.info("Solicitud ARCO descartada por honeypot")
        messages.success(request, "Recibimos tu solicitud. Te responderemos dentro de un plazo máximo de 72 horas.")
        return redirect(redirect_url)

    token = request.POST.get("cf-turnstile-response")
    if not verify_turnstile(token, get_client_ip(request)):
        messages.error(request, "No pudimos verificar que no eres un robot, intenta de nuevo.")
        return redirect(redirect_url)

    datos = {k: v for k, v in form.cleaned_data.items() if k != "pagina_web"}
    try:
        enviar_email_arco(**datos)
    except (smtplib.SMTPException, OSError):
        logger.exception("Fallo al enviar el correo de solicitud ARCO")
        messages.error(request, "No pudimos enviar tu solicitud, intenta nuevamente en unos minutos.")
        return redirect(redirect_url)

    messages.success(request, "Recibimos tu solicitud. Te responderemos dentro de un plazo máximo de 72 horas.")
    return redirect(redirect_url)


def health_check(request):
    # Shallow on purpose, this is what Railway polls to gate deploys.
    return HttpResponse("OK")


@never_cache
def health_check_db(request):
    """Deep health check for uptime monitors: pings PostgreSQL directly."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok", "database": "reachable"})
