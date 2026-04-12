from django.contrib.auth import authenticate, login
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render

from .decorators import requiere_rol, tenant_member_required
from .models import Dispositivo, Nave


def tenant_home_placeholder(request, slug):
    return HttpResponse(f"Home tenant placeholder para {slug}.", status=200)


def kiosco_home_placeholder(request, slug):
    return HttpResponse(f"Kiosco home placeholder para {slug}.", status=200)


def login_tierra(request, slug):
    tenant = getattr(request, "naviera", None)

    if request.user.is_authenticated and getattr(request.user, "naviera", None) == tenant:
        return redirect(f"/{slug}/")

    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        usuario = authenticate(request, email=email, password=password)
        if usuario is not None:
            login(request, usuario)
            return redirect(f"/{slug}/")

        return render(
            request,
            "inventory/login_tierra.html",
            {"error": "Credenciales inválidas."},
        )

    return render(request, "inventory/login_tierra.html")


def login_kiosco(request, slug):
    tenant = getattr(request, "naviera", None)

    if request.user.is_authenticated and getattr(request.user, "naviera", None) == tenant:
        return redirect(f"/{slug}/kiosco/")
    
    if request.method == "POST":
        rut = request.POST.get("rut")
        pin = request.POST.get("pin")
        dispositivo_token = request.POST.get("dispositivo_token")

        usuario = authenticate(
            request,
            rut=rut,
            pin=pin,
            naviera_id=getattr(request.naviera, "id", None),
            dispositivo_token=dispositivo_token,
        )
        if usuario is not None:
            dispositivo = getattr(usuario, "_dispositivo_autenticado", None)
            request.session["nave_id"] = getattr(dispositivo, "nave_id", None)
            login(request, usuario)
            return redirect(f"/{slug}/kiosco/")

        return render(
            request,
            "inventory/login_kiosco.html",
            {"error": "Acceso denegado."},
        )

    return render(request, "inventory/login_kiosco.html")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def setup_kiosco(request, slug):
    naviera = request.naviera

    # 2. PROCESAMIENTO DEL PAYLOAD (POST)
    if request.method == "POST":
        nombre_dispositivo = request.POST.get("nombre_dispositivo")
        nave_id = request.POST.get("nave_id")

        # Validación de Jurisdicción (Previene IDOR)
        nave = None
        if nave_id:
            try:
                nave = Nave.objects.get(id=nave_id, naviera=naviera)
            except Nave.DoesNotExist:
                return HttpResponseForbidden("Intento de Brecha: La nave solicitada no pertenece a su tenant.")

        # Fabricación del Hardware Binding
        dispositivo = Dispositivo(naviera=naviera, nave=nave, nombre=nombre_dispositivo)
        token_plano = dispositivo.generar_nuevo_token()
        dispositivo.save()

        # Renderizamos la vista de éxito inyectando el token secreto
        contexto = {"token_plano": token_plano, "dispositivo": dispositivo}
        return render(request, "inventory/kiosco_tatuado.html", contexto)

    # 3. RENDERIZADO DEL FORMULARIO (GET)
    naves = Nave.objects.filter(naviera=naviera, is_active=True)
    return render(request, "inventory/kiosco_setup.html", {"naves": naves})
