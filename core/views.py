import logging
import smtplib

from django.contrib import messages
from django.shortcuts import redirect, render
from django.http import HttpResponse, JsonResponse, QueryDict
from django.db import connection
from django.urls import reverse
from django.views.decorators.cache import never_cache

from core.forms import ContactoForm
from core.services import enviar_email_contacto
from sitrep.accounts.models import Naviera

logger = logging.getLogger(__name__)

CONTACTO_SESSION_KEY = "contacto_form_data"


def homepage(request):
    navieras = Naviera.objects.filter(slug__isnull=False).order_by("nombre")
    stashed = request.session.pop(CONTACTO_SESSION_KEY, None)
    contacto_form = ContactoForm(QueryDict(stashed)) if stashed else ContactoForm()
    return render(request, "homepage.html", {"navieras": navieras, "contacto_form": contacto_form})


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

    try:
        enviar_email_contacto(**form.cleaned_data)
    except (smtplib.SMTPException, OSError):
        logger.exception("Fallo al enviar el correo de contacto")
        messages.error(request, "No pudimos enviar tu mensaje, intenta nuevamente en unos minutos.")
        return redirect(f"{reverse('homepage')}#contacto")

    messages.success(request, "Gracias, te contactaremos a la brevedad.")
    return redirect(f"{reverse('homepage')}#contacto")


def legal_terminos(request):
    return render(request, "legal/terminos.html")


def legal_privacidad(request):
    return render(request, "legal/privacidad.html")


def legal_dpa(request):
    return render(request, "legal/dpa.html")

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
