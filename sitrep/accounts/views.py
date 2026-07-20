import re

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import redirect, render

from core.decorators import requiere_admin, requiere_admin_capitan, requiere_rol
from core.permissions import ROLES_GESTION_USUARIOS, ROLES_TIERRA
from core.utils import get_client_ip, hit_rate_limit, paginate, throttle, verify_turnstile
from sitrep.accounts.audit import registrar_acceso
from sitrep.accounts.decorators import tenant_member_required
from sitrep.accounts.services import (
    notificar_ayuda_pin,
    resolver_usuario_reset,
    solicitar_recuperacion,
)
from sitrep.fleet.models import Tripulacion
from sitrep.fleet.services import FleetQueryService
from sitrep.inspection.services import TenantQueryService  # ponytail: migrate to AccountsQueryService after full accounts segregation

Usuario = get_user_model()
SESSION_COOKIE_AGE_RECORDADO = 1209600  # 2 semanas, igual al default de Django


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
    return render(request, "accounts/login_unificado.html", payload)


def login_unificado(request, slug, modo_default="tierra"):
    tenant = getattr(request, "naviera", None)
    modo = _normalizar_modo_login(
        (request.POST.get("modo") or request.POST.get("mode"))
        if request.method == "POST"
        else request.GET.get("modo"),
        modo_default=modo_default,
    )

    if request.user.is_authenticated and getattr(request.user, "naviera", None) == tenant:
        if modo == "mar" or getattr(request.user, "rol", None) not in ROLES_TIERRA:
            return redirect(f"/{slug}/kiosco/")
        return redirect(f"/{slug}/")

    if request.method == "POST":
        # Scope por modo (ej. login_mar, login_tierra): cada modo mantiene su propio
        # budget, mar en particular porque cada intento corre check_password por cada
        # dispositivo de la naviera (KioscoTenantBackend) y es amplificador de DoS.
        # Un solo chequeo acá cubre cualquier modo nuevo que se agregue sin repetirlo.
        if hit_rate_limit(f"login_{modo}", request, limit=10, window_seconds=60):
            return _render_login_unificado(
                request, slug, modo, error="Demasiados intentos. Espera un momento."
            )

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
                return _render_login_unificado(
                    request, slug, modo, limpiar_token=True,
                    error="Este dispositivo fue revocado. Contacte a su supervisor.",
                )

            return _render_login_unificado(request, slug, modo, error="Acceso denegado.")

        elif modo == "tierra":
            email = request.POST.get("email")
            password = request.POST.get("password")

            usuario = authenticate(request, email=email, password=password)
            if usuario is not None:
                recordar = bool(request.POST.get("recordar"))
                request.session.set_expiry(SESSION_COOKIE_AGE_RECORDADO if recordar else 0)
                login(request, usuario)
                return redirect(f"/{slug}/")

            return _render_login_unificado(request, slug, modo, error="Credenciales inválidas.")

        else:
            # _normalizar_modo_login solo devuelve "mar" o "tierra"; si esto se
            # dispara, algo cambió esa garantía y no queremos caer en la rama
            # de tierra por default con un modo no contemplado.
            raise ValueError(f"modo de login desconocido: {modo!r}")

    return _render_login_unificado(request, slug, modo)


def logout_kiosco(request, slug):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    logout(request)
    return redirect(f"/{slug}/login/?modo=mar")


def redirect_kiosco_login(request, slug):
    return redirect(f"/{slug}/login/?modo=mar")


@throttle("recuperar_pass", limit=5, window_seconds=600)
def solicitar_recuperacion_password(request, slug):
    tenant = getattr(request, "naviera", None)
    enviado = False
    email = ""
    error = None

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        if not verify_turnstile(request.POST.get("cf-turnstile-response"), get_client_ip(request)):
            error = "No pudimos verificar que no eres un robot, intenta de nuevo."
        elif email:
            solicitar_recuperacion(request, email)
            enviado = True

    return render(
        request,
        "accounts/recuperar_password.html",
        {
            "slug": slug,
            "naviera": tenant,
            "email": email,
            "enviado": enviado,
            "error": error,
            "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
        },
    )


@throttle("confirmar_pass", limit=10, window_seconds=600)
def confirmar_recuperacion_password(request, slug, uidb64, token):
    tenant = getattr(request, "naviera", None)
    usuario = resolver_usuario_reset(request, uidb64, token)
    if usuario is None:
        return render(
            request,
            "accounts/recuperar_password_confirmar.html",
            {"slug": slug, "naviera": tenant, "enlace_invalido": True},
        )

    if request.method == "POST":
        password = request.POST.get("password") or ""
        confirmacion = request.POST.get("password_confirmacion") or ""
        error = None
        if password != confirmacion:
            error = "Las contraseñas no coinciden."
        else:
            try:
                validate_password(password, usuario)
            except ValidationError as exc:
                error = " ".join(exc.messages)
        if error:
            return render(
                request,
                "accounts/recuperar_password_confirmar.html",
                {"slug": slug, "naviera": tenant, "error": error},
            )
        usuario.set_password(password)
        usuario.save(update_fields=["password"])  # invalida el token: embebe el hash anterior
        return render(
            request,
            "accounts/recuperacion_password_exito.html",
            {"slug": slug, "naviera": tenant},
        )

    return render(
        request,
        "accounts/recuperar_password_confirmar.html",
        {"slug": slug, "naviera": tenant},
    )


@throttle("ayuda_pin", limit=5, window_seconds=600)
def solicitar_ayuda_pin(request, slug):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    rut = _normalizar_rut(request.POST.get("rut") or "")
    dispositivo_token = request.POST.get("dispositivo_token")
    if rut:
        # El aviso solo procede desde un kiosco autorizado cuyo tripulante sea el
        # del rut; el gate y la auditoría viven en el servicio.
        notificar_ayuda_pin(request, rut, dispositivo_token)

    return render(
        request,
        "accounts/ayuda_pin_exito.html",
        {"slug": slug, "naviera": getattr(request, "naviera", None)},
    )


@tenant_member_required
def logout_tierra(request, slug):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    logout(request)
    return redirect("inventory:login_tierra", slug=slug)


@tenant_member_required
@requiere_rol(*ROLES_GESTION_USUARIOS)
def listar_usuarios(request, slug):
    q = request.GET.get("q", "").strip()
    rol = request.GET.get("rol", "").strip()
    usuarios = TenantQueryService.get_usuarios_del_tenant(request.naviera)
    if q:
        usuarios = usuarios.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(rut__icontains=q) | Q(email__icontains=q)
        )
    if rol:
        usuarios = usuarios.filter(rol=rol)
    _params = request.GET.copy()
    _params.pop("page", None)
    page_obj = paginate(usuarios.order_by("first_name", "last_name"), request.GET.get("page"), 10)
    registrar_acceso(
        request, "read", "usuarios",
        detalle=f"query_count={page_obj.paginator.count} page={page_obj.number}",
    )
    return render(
        request,
        "accounts/usuarios_lista.html",
        {
            "page_obj": page_obj,
            "pagination_params": _params.urlencode(),
            "q": q,
            "rol": rol,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_admin
def crear_usuario(request, slug):
    if request.method == "GET":
        return render(
            request,
            "accounts/usuario_form.html",
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
            "accounts/usuario_form.html",
            {
                "error": "Formato de RUT inválido. Use el formato 12.345.678-9.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    if Usuario.objects.filter(naviera=request.naviera, rut=rut).exists():
        return render(
            request,
            "accounts/usuario_form.html",
            {
                "error": "El RUT ya existe en esta naviera.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    requiere_pin = rol in {"mar", "capitan"}
    requiere_password = rol != "mar"

    if requiere_pin and not raw_pin:
        return render(
            request,
            "accounts/usuario_form.html",
            {
                "error": "El PIN es obligatorio para este rol.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    if requiere_pin and not _pin_valido_4_digitos(raw_pin):
        return render(
            request,
            "accounts/usuario_form.html",
            {
                "error": "El PIN debe ser de 4 dígitos numéricos.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    raw_password = (request.POST.get("password") or "").strip()
    if requiere_password and not raw_password:
        return render(
            request,
            "accounts/usuario_form.html",
            {
                "error": "La contraseña es obligatoria para este rol.",
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
    if requiere_password:
        usuario.set_password(raw_password)
    else:
        usuario.set_unusable_password()

    usuario.save()
    return redirect(f"/{slug}/usuarios/")


@tenant_member_required
@requiere_admin
def desactivar_usuario(request, slug, id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    usuario = TenantQueryService.get_usuario_del_tenant(request.naviera, id)
    if request.user == usuario:
        return HttpResponseForbidden("No puedes desactivarte a ti mismo.")

    usuario.delete()
    return redirect(f"/{slug}/usuarios/")


@tenant_member_required
@requiere_admin_capitan
def cambiar_pin(request, slug, id):
    if request.user.id != id:
        naves_scope = FleetQueryService.get_naves_scope(request.user, request.naviera)
        if naves_scope is not None:
            # El capitán puede resetear el PIN de la tripulación de sus propias naves.
            es_tripulante_propio = Tripulacion.objects.filter(
                usuario_id=id,
                nave__in=naves_scope,
            ).exists()
            if not es_tripulante_propio:
                return HttpResponseForbidden("Acceso denegado.")

    usuario = TenantQueryService.get_usuario_activo_del_tenant(request.naviera, id)

    if request.method == "GET":
        return render(
            request,
            "accounts/cambiar_pin.html",
            {"usuario": usuario, "slug": slug},
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    raw_pin = (request.POST.get("pin") or "").strip()
    if not _pin_valido_4_digitos(raw_pin):
        return render(
            request,
            "accounts/cambiar_pin.html",
            {
                "usuario": usuario,
                "slug": slug,
                "error": "El PIN debe ser de 4 dígitos numéricos.",
            },
        )

    usuario.set_pin(raw_pin)
    usuario.save(update_fields=["pin_kiosco"])
    return redirect(f"/{slug}/usuarios/")
