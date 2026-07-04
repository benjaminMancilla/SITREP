import re

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import redirect, render

from sitrep.accounts.decorators import requiere_rol, tenant_member_required
from sitrep.inspection.services import TenantQueryService  # ponytail: migrate to AccountsQueryService after full accounts segregation

Usuario = get_user_model()


def _normalizar_rut(rut: str) -> str:
    return rut.strip().upper().replace(".", "").replace(" ", "")


def _rut_valido(rut: str) -> bool:
    """Valida formato RUT chileno: dígitos con puntos opcionales + guión + dígito verificador."""
    rut = _normalizar_rut(rut)
    return bool(re.match(r"^\d{7,8}-[\dK]$", rut))


def _pin_valido_4_digitos(raw_pin):
    return bool(raw_pin) and len(raw_pin) == 4 and raw_pin.isdigit()


def _normalizar_modo_login(modo, modo_default="tierra"):
    modo_default_normalizado = "mar" if modo_default == "mar" else "tierra"
    if modo in {"tierra", "mar"}:
        return modo
    return modo_default_normalizado


def _render_login_unificado(request, slug, modo, **contexto):
    payload = {
        "slug": slug,
        "modo": modo,
        "naviera": getattr(request, "naviera", None),
    }
    payload.update(contexto)
    return render(request, "inventory/login_unificado.html", payload)


def login_unificado(request, slug, modo_default="tierra"):
    tenant = getattr(request, "naviera", None)
    modo = _normalizar_modo_login(
        (request.POST.get("modo") or request.POST.get("mode"))
        if request.method == "POST"
        else request.GET.get("modo"),
        modo_default=modo_default,
    )

    if request.user.is_authenticated and getattr(request.user, "naviera", None) == tenant:
        if modo == "mar":
            return redirect(f"/{slug}/kiosco/")
        return redirect(f"/{slug}/")

    if request.method == "POST":
        if modo == "mar":
            rut = _normalizar_rut(request.POST.get("rut") or "")
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

            if getattr(request, "_dispositivo_revocado", False):
                return _render_login_unificado(request, slug, modo, limpiar_token=True)

            return _render_login_unificado(request, slug, modo, error="Acceso denegado.")

        email = request.POST.get("email")
        password = request.POST.get("password")

        usuario = authenticate(request, email=email, password=password)
        if usuario is not None:
            login(request, usuario)
            return redirect(f"/{slug}/")

        return _render_login_unificado(request, slug, modo, error="Credenciales inválidas.")

    return _render_login_unificado(request, slug, modo)


def logout_kiosco(request, slug):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    logout(request)
    return redirect(f"/{slug}/login/?modo=mar")


def redirect_kiosco_login(request, slug):
    return redirect(f"/{slug}/login/?modo=mar")


@tenant_member_required
def logout_tierra(request, slug):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    logout(request)
    return redirect("inventory:login_tierra", slug=slug)


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def listar_usuarios(request, slug):
    usuarios = TenantQueryService.get_usuarios_del_tenant(request.naviera)
    return render(
        request,
        "inventory/usuarios_lista.html",
        {
            "usuarios": usuarios,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def crear_usuario(request, slug):
    if request.method == "GET":
        return render(
            request,
            "inventory/usuario_form.html",
            {
                "slug": slug,
                "form_data": {},
            },
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    rut_input = (request.POST.get("rut") or "").strip()
    rut = _normalizar_rut(rut_input)
    email = (request.POST.get("email") or "").strip() or None
    rol = (request.POST.get("rol") or "").strip()
    first_name = (request.POST.get("first_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    raw_pin = (request.POST.get("pin") or "").strip()
    form_data = {
        "rut": rut_input,
        "email": email or "",
        "rol": rol,
        "first_name": first_name,
        "last_name": last_name,
    }

    if not _rut_valido(rut_input):
        return render(
            request,
            "inventory/usuario_form.html",
            {
                "error": "Formato de RUT inválido. Use el formato 12.345.678-9.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    if Usuario.objects.filter(naviera=request.naviera, rut=rut).exists():
        return render(
            request,
            "inventory/usuario_form.html",
            {
                "error": "El RUT ya existe en esta naviera.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    requiere_pin = rol in {"mar", "capitan"}
    if requiere_pin and not raw_pin:
        return render(
            request,
            "inventory/usuario_form.html",
            {
                "error": "El PIN es obligatorio para este rol.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    if requiere_pin and not _pin_valido_4_digitos(raw_pin):
        return render(
            request,
            "inventory/usuario_form.html",
            {
                "error": "El PIN debe ser de 4 dígitos numéricos.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    usuario = Usuario(
        naviera=request.naviera,
        rut=rut,
        email=email,
        rol=rol,
        first_name=first_name,
        last_name=last_name,
    )

    if requiere_pin:
        usuario.set_pin(raw_pin)
        usuario.set_unusable_password()
    else:
        raw_password = (request.POST.get("password") or "").strip()
        if not raw_password:
            return render(
                request,
                "inventory/usuario_form.html",
                {
                    "error": "La contraseña es obligatoria para este rol.",
                    "slug": slug,
                    "form_data": form_data,
                },
            )
        usuario.set_password(raw_password)

    usuario.save()
    return redirect(f"/{slug}/usuarios/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def desactivar_usuario(request, slug, id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    usuario = TenantQueryService.get_usuario_del_tenant(request.naviera, id)
    if request.user == usuario:
        return HttpResponseForbidden("No puedes desactivarte a ti mismo.")

    usuario.delete()
    return redirect(f"/{slug}/usuarios/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def cambiar_pin(request, slug, id):
    if request.user.rol == "capitan" and request.user.id != id:
        return HttpResponseForbidden("Acceso denegado.")

    usuario = TenantQueryService.get_usuario_activo_del_tenant(request.naviera, id)

    if request.method == "GET":
        return render(
            request,
            "inventory/cambiar_pin.html",
            {"usuario": usuario, "slug": slug},
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    raw_pin = (request.POST.get("pin") or "").strip()
    if not _pin_valido_4_digitos(raw_pin):
        return render(
            request,
            "inventory/cambiar_pin.html",
            {
                "usuario": usuario,
                "slug": slug,
                "error": "El PIN debe ser de 4 dígitos numéricos.",
            },
        )

    usuario.set_pin(raw_pin)
    usuario.save(update_fields=["pin_kiosco"])
    return redirect(f"/{slug}/usuarios/")
