from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.db import connection
from django.views.decorators.cache import never_cache

from sitrep.accounts.models import Naviera


def homepage(request):
    navieras = Naviera.objects.filter(slug__isnull=False).order_by("nombre")
    return render(request, "homepage.html", {"navieras": navieras})


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
