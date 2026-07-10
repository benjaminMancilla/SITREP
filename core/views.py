import logging
import smtplib

from django.contrib import messages
from django.shortcuts import redirect, render
from django.http import HttpResponse, JsonResponse
from django.db import connection
from django.urls import reverse
from django.views.decorators.cache import never_cache

from core.forms import ContactoForm
from core.services import enviar_email_contacto
from sitrep.accounts.models import Naviera

logger = logging.getLogger(__name__)


def homepage(request):
    navieras = Naviera.objects.filter(slug__isnull=False).order_by("nombre")
    return render(request, "homepage.html", {"navieras": navieras, "contacto_form": ContactoForm()})


def contacto(request):
    if request.method != "POST":
        return redirect("homepage")

    form = ContactoForm(request.POST)
    if form.is_valid():
        try:
            enviar_email_contacto(**form.cleaned_data)
        except (smtplib.SMTPException, OSError):
            logger.exception("Fallo al enviar el correo de contacto")
            messages.error(request, "No pudimos enviar tu mensaje, intenta nuevamente en unos minutos.")
            return redirect(f"{reverse('homepage')}#contacto")
        messages.success(request, "Gracias, te contactaremos a la brevedad.")
        return redirect(f"{reverse('homepage')}#contacto")

    messages.error(request, "Revisa los datos del formulario e inténtalo de nuevo.")
    navieras = Naviera.objects.filter(slug__isnull=False).order_by("nombre")
    return render(request, "homepage.html", {"navieras": navieras, "contacto_form": form})


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
