from decimal import Decimal, InvalidOperation

from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import Http404, HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import redirect, render

from core.decorators import requiere_admin, requiere_admin_capitan, requiere_tierra
from core.utils import paginate
from sitrep.accounts.decorators import tenant_member_required
from sitrep.fleet.models import Dispositivo, Nave, Tripulacion
from sitrep.fleet.services import FleetQueryService
from sitrep.inspection.services import TenantQueryService  # ponytail: migrate to FleetQueryService/AccountsQueryService after full segregation


@tenant_member_required
@requiere_tierra
def listar_naves(request, slug):
    q = request.GET.get("q", "").strip()
    naves = TenantQueryService.get_naves_activas(request.naviera).annotate(
        periodos_abiertos=Count(
            "periodos",
            filter=Q(periodos__estado__in=TenantQueryService.ESTADOS_ABIERTOS),
            distinct=True,
        ),
        fallos_activos=Count(
            "matriz_recursos",
            filter=Q(
                matriz_recursos__es_visible=True,
                matriz_recursos__ultimo_estado_operativo=False,
            ),
            distinct=True,
        ),
        fallos_nuevos=Count(
            "matriz_recursos",
            filter=Q(
                matriz_recursos__es_visible=True,
                matriz_recursos__es_fallo_nuevo=True,
            ),
            distinct=True,
        ),
    )
    naves_scope = FleetQueryService.get_naves_scope(request.user, request.naviera)
    if naves_scope is not None:
        naves = naves.filter(id__in=naves_scope)
    if q:
        naves = naves.filter(Q(nombre__icontains=q) | Q(matricula__icontains=q))
    _params = request.GET.copy()
    _params.pop("page", None)
    return render(
        request,
        "fleet/naves_lista.html",
        {
            "page_obj": paginate(naves.order_by("nombre"), request.GET.get("page"), 20),
            "pagination_params": _params.urlencode(),
            "q": q,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_admin
def crear_nave(request, slug):
    if request.method == "GET":
        return render(
            request,
            "fleet/nave_form.html",
            {
                "slug": slug,
                "form_data": {},
            },
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    nombre = (request.POST.get("nombre") or "").strip()
    matricula = (request.POST.get("matricula") or "").strip()
    eslora = (request.POST.get("eslora") or "").strip()
    arqueo_bruto = (request.POST.get("arqueo_bruto") or "").strip()
    capacidad_personas = (request.POST.get("capacidad_personas") or "").strip()
    form_data = {
        "nombre": nombre,
        "matricula": matricula,
        "eslora": eslora,
        "arqueo_bruto": arqueo_bruto,
        "capacidad_personas": capacidad_personas,
    }

    try:
        Nave.objects.create(
            naviera=request.naviera,
            nombre=nombre,
            matricula=matricula,
            eslora=eslora,
            arqueo_bruto=arqueo_bruto,
            capacidad_personas=capacidad_personas,
        )
    except IntegrityError:
        return render(
            request,
            "fleet/nave_form.html",
            {
                "error": "La matrícula ya existe en esta naviera.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    return redirect(f"/{slug}/naves/")


@tenant_member_required
@requiere_admin
def editar_nave(request, slug, nave_id):
    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)

    if request.method == "GET":
        return render(
            request,
            "fleet/nave_form.html",
            {
                "slug": slug,
                "nave": nave,
                "editando": True,
                "form_data": {
                    "nombre": nave.nombre,
                    "matricula": nave.matricula,
                    "eslora": nave.eslora,
                    "arqueo_bruto": nave.arqueo_bruto,
                    "capacidad_personas": nave.capacidad_personas,
                },
            },
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    nombre = (request.POST.get("nombre") or "").strip()
    eslora_raw = (request.POST.get("eslora") or "").strip()
    arqueo_bruto_raw = (request.POST.get("arqueo_bruto") or "").strip()
    capacidad_personas_raw = (request.POST.get("capacidad_personas") or "").strip()
    form_data = {
        "nombre": nombre,
        "matricula": nave.matricula,
        "eslora": eslora_raw,
        "arqueo_bruto": arqueo_bruto_raw,
        "capacidad_personas": capacidad_personas_raw,
    }

    try:
        eslora = Decimal(eslora_raw)
        arqueo_bruto = int(arqueo_bruto_raw)
        capacidad_personas = int(capacidad_personas_raw)
    except (InvalidOperation, TypeError, ValueError):
        return render(
            request,
            "fleet/nave_form.html",
            {
                "error": "Eslora, arqueo bruto y capacidad deben ser numéricos válidos.",
                "slug": slug,
                "nave": nave,
                "editando": True,
                "form_data": form_data,
            },
        )

    nave.nombre = nombre
    nave.eslora = eslora
    nave.arqueo_bruto = arqueo_bruto
    nave.capacidad_personas = capacidad_personas
    nave.save(update_fields=["nombre", "eslora", "arqueo_bruto", "capacidad_personas"])

    return redirect(f"/{slug}/naves/")


@tenant_member_required
@requiere_admin
def desactivar_nave(request, slug, nave_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    nave = TenantQueryService.get_nave(request.naviera, nave_id)
    if not nave.is_active:
        return redirect(f"/{slug}/naves/")

    nave.delete()
    return redirect(f"/{slug}/naves/")


@tenant_member_required
@requiere_tierra
def listar_dispositivos(request, slug):
    q = request.GET.get("q", "").strip()
    dispositivos = TenantQueryService.get_dispositivos(request.naviera)
    naves_scope = FleetQueryService.get_naves_scope(request.user, request.naviera)
    if naves_scope is not None:
        dispositivos = dispositivos.filter(nave__in=naves_scope)
    if q:
        dispositivos = dispositivos.filter(Q(nombre__icontains=q) | Q(nave__nombre__icontains=q))
    _params = request.GET.copy()
    _params.pop("page", None)
    return render(
        request,
        "fleet/dispositivos_lista.html",
        {
            "page_obj": paginate(dispositivos.order_by("nave__nombre", "nombre"), request.GET.get("page"), 10),
            "pagination_params": _params.urlencode(),
            "q": q,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_admin_capitan
def setup_kiosco(request, slug):
    if request.method == "POST":
        nombre_dispositivo = request.POST.get("nombre_dispositivo")
        nave_id = request.POST.get("nave_id")

        if not nave_id:
            return HttpResponseForbidden("Debe asignar el dispositivo a una nave.")

        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
        if not FleetQueryService.nave_en_scope(request.user, request.naviera, nave.id):
            return HttpResponseForbidden("Acceso denegado.")

        dispositivo = Dispositivo(naviera=request.naviera, nave=nave, nombre=nombre_dispositivo)
        token_plano = dispositivo.generar_nuevo_token()
        dispositivo.save()

        contexto = {"token_plano": token_plano, "dispositivo": dispositivo}
        return render(request, "fleet/kiosco_tatuado.html", contexto)

    naves = TenantQueryService.get_naves_activas(request.naviera)
    naves_scope = FleetQueryService.get_naves_scope(request.user, request.naviera)
    if naves_scope is not None:
        naves = naves.filter(id__in=naves_scope)
    return render(request, "fleet/kiosco_setup.html", {"naves": naves})


@tenant_member_required
@requiere_admin_capitan
def revocar_dispositivo(request, slug, id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    dispositivo = TenantQueryService.get_dispositivo(request.naviera, id)
    if not FleetQueryService.nave_en_scope(request.user, request.naviera, dispositivo.nave_id):
        return HttpResponseForbidden("Acceso denegado.")

    if not dispositivo.is_active:
        return redirect(f"/{slug}/kiosco/hardware/")

    dispositivo.is_active = False
    dispositivo.save(update_fields=["is_active"])

    return redirect(f"/{slug}/kiosco/hardware/")


@tenant_member_required
@requiere_tierra
def listar_tripulacion(request, slug, nave_id):
    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    if not FleetQueryService.nave_en_scope(request.user, request.naviera, nave.id):
        return HttpResponseForbidden("Acceso denegado.")
    q = request.GET.get("q", "").strip()
    tripulacion = TenantQueryService.get_tripulacion_activa_de_nave(request.naviera, nave_id)
    usuarios_asignados_ids = tripulacion.values_list("usuario_id", flat=True)
    usuarios_disponibles = TenantQueryService.get_usuarios_del_tenant(request.naviera).exclude(
        id__in=usuarios_asignados_ids
    )
    if q:
        tripulacion = tripulacion.filter(
            Q(usuario__first_name__icontains=q) | Q(usuario__last_name__icontains=q) | Q(usuario__rut__icontains=q)
        )
    _params = request.GET.copy()
    _params.pop("page", None)
    return render(
        request,
        "fleet/tripulacion_lista.html",
        {
            "nave": nave,
            "page_obj": paginate(tripulacion, request.GET.get("page"), 20),
            "pagination_params": _params.urlencode(),
            "q": q,
            "usuarios_disponibles": usuarios_disponibles,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_admin_capitan
def agregar_tripulante(request, slug, nave_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    if not FleetQueryService.nave_en_scope(request.user, request.naviera, nave.id):
        return HttpResponseForbidden("Acceso denegado.")

    usuario_id = request.POST.get("usuario_id")
    usuario = TenantQueryService.get_usuario_activo_del_tenant(request.naviera, usuario_id)
    if request.user.rol == "capitan" and usuario == request.user:
        return HttpResponseForbidden("No puedes agregarte a ti mismo como tripulante.")

    try:
        Tripulacion.objects.create(usuario=usuario, nave=nave)
    except IntegrityError:
        pass

    return redirect(f"/{slug}/naves/{nave_id}/tripulacion/")


@tenant_member_required
@requiere_admin_capitan
def remover_tripulante(request, slug, nave_id, tripulacion_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    if not FleetQueryService.nave_en_scope(request.user, request.naviera, nave.id):
        return HttpResponseForbidden("Acceso denegado.")

    try:
        tripulacion = Tripulacion.objects.get(id=tripulacion_id, nave=nave)
    except Tripulacion.DoesNotExist as exc:
        raise Http404("Recurso no encontrado.") from exc

    if request.user.rol == "capitan" and tripulacion.usuario == request.user:
        return HttpResponseForbidden("No puedes removerte a ti mismo de la tripulación.")

    tripulacion.delete()
    return redirect(f"/{slug}/naves/{nave_id}/tripulacion/")
