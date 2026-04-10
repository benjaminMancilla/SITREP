"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse


def health_check(request):
    return HttpResponse("SITREP en linea y operativo.", status=200)


def login_tierra_placeholder(request, slug):
    return HttpResponse(f"Tierra login placeholder para {slug}.", status=200)


def login_kiosco_placeholder(request, slug):
    return HttpResponse(f"Kiosco login placeholder para {slug}.", status=200)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('<slug:slug>/login/', login_tierra_placeholder, name='login_tierra'),
    path('<slug:slug>/kiosco/login/', login_kiosco_placeholder, name='login_kiosco'),
    path('<slug:slug>/', include('inventory.urls')),
]
