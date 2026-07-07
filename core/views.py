from django.shortcuts import render
from django.http import HttpResponse

from sitrep.accounts.models import Naviera


def homepage(request):
    navieras = Naviera.objects.filter(slug__isnull=False).order_by("nombre")
    return render(request, "homepage.html", {"navieras": navieras})

def health_check(request):
    return HttpResponse("OK")
