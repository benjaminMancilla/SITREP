from django.shortcuts import render

from inventory.models import Naviera


def homepage(request):
    navieras = Naviera.objects.filter(slug__isnull=False).order_by("nombre")
    return render(request, "homepage.html", {"navieras": navieras})
