import json
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib.auth import authenticate, login, logout
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Max, Q
from django.db.models.functions import Coalesce, Greatest
from django.http import Http404, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from .decorators import requiere_rol, tenant_member_required
from .models import (
    Dispositivo,
    FichaRegistro,
    MatrizNaveRecurso,
    Nave,
    Periodicidad,
    PeriodoRevision,
    Recurso,
    Tripulacion,
    Usuario,
)
from .services import MotorFichas, MotorPeriodos, TenantQueryService

logger = logging.getLogger(__name__)


def _normalizar_rut(rut: str) -> str:
    return rut.strip().upper().replace(".", "").replace(" ", "")


def _rut_valido(rut: str) -> bool:
    """Valida formato RUT chileno: dígitos con puntos opcionales + guión + dígito verificador."""
    rut = _normalizar_rut(rut)
    return bool(re.match(r"^\d{7,8}-[\dK]$", rut))


def _pin_valido_4_digitos(raw_pin):
    return bool(raw_pin) and len(raw_pin) == 4 and raw_pin.isdigit()


ROLES_API_KIOSCO = {"mar", "capitan", "tierra", "admin_naviera", "admin_sitrep"}


def _json_error(mensaje, status):
    return JsonResponse({"error": mensaje}, status=status)


def _validar_rol_api_kiosco(request):
    if getattr(request.user, "rol", None) not in ROLES_API_KIOSCO:
        return _json_error("Acceso denegado: rango insuficiente.", 403)
    return None


def _obtener_nave_activa_desde_sesion(request):
    nave_id = request.session.get("nave_id")
    if not nave_id:
        return None, _json_error("Sesión de nave no disponible.", 403)

    try:
        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    except Http404:
        return None, _json_error("Nave no encontrada.", 404)

    return nave, None


def _obtener_periodo_de_nave(nave, periodo_id):
    try:
        return PeriodoRevision.objects.select_related("periodicidad").get(id=periodo_id, nave=nave)
    except PeriodoRevision.DoesNotExist:
        return None


def _contar_fichas_completas(fichas):
    return sum(1 for ficha in fichas if MotorPeriodos._es_ficha_completa(ficha))


def _contar_fichas_completas_por_periodo(periodo_ids):
    conteos = {periodo_id: 0 for periodo_id in periodo_ids}
    if not periodo_ids:
        return conteos

    fichas = FichaRegistro.objects.filter(periodo_id__in=periodo_ids).select_related("recurso")
    for ficha in fichas:
        if MotorPeriodos._es_ficha_completa(ficha):
            conteos[ficha.periodo_id] += 1
    return conteos


def _obtener_filtros_historial_desde_request(request):
    fecha_desde_str = request.GET.get("fecha_desde", "")
    fecha_hasta_str = request.GET.get("fecha_hasta", "")
    estado_filtro = request.GET.get("estado", "")
    periodicidad_id_filtro = request.GET.get("periodicidad", "")

    fecha_desde = None
    fecha_hasta = None
    try:
        if fecha_desde_str:
            fecha_desde = date.fromisoformat(fecha_desde_str)
        if fecha_hasta_str:
            fecha_hasta = date.fromisoformat(fecha_hasta_str)
    except ValueError:
        fecha_desde = None
        fecha_hasta = None

    return {
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "fecha_desde_str": fecha_desde_str,
        "fecha_hasta_str": fecha_hasta_str,
        "estado_filtro": estado_filtro,
        "periodicidad_id_filtro": periodicidad_id_filtro,
    }


def _construir_periodos_detalle(nave, periodos):
    periodos_detalle = []
    # TODO: optimizar con annotate() y prefetch_related en Fase 4
    for periodo in periodos:
        fichas = list(TenantQueryService.get_fichas_de_periodo(periodo).order_by("recurso__nombre"))
        matrices = list(
            TenantQueryService.get_recursos_visibles_de_nave_en_periodo(nave, periodo).order_by(
                "recurso__nombre"
            )
        )
        total_recursos = len(matrices)
        fichas_count = _contar_fichas_completas(fichas)
        fichas_por_recurso_id = {ficha.recurso_id: ficha for ficha in fichas}
        registros = []
        fallos_count = 0

        for matriz in matrices:
            ficha = fichas_por_recurso_id.get(matriz.recurso_id)
            if ficha is None:
                registros.append(
                    {
                        "tipo": "pendiente",
                        "recurso": matriz.recurso,
                    }
                )
                continue

            if ficha.estado_operativo is False:
                fallos_count += 1

            registros.append(
                {
                    "tipo": "ficha",
                    "recurso": matriz.recurso,
                    "ficha": ficha,
                    "estado_operativo": ficha.estado_operativo,
                }
            )

        periodos_detalle.append(
            {
                "periodo": periodo,
                "fichas": fichas,
                "registros": registros,
                "total_recursos": total_recursos,
                "fichas_count": fichas_count,
                "fallos_count": fallos_count,
                "has_fallos": fallos_count > 0,
                "avance_pct": int((fichas_count * 100) / total_recursos) if total_recursos else 0,
            }
        )
    return periodos_detalle


def _construir_recursos_lista_periodo(nave, periodo, slug=None):
    matrices = TenantQueryService.get_recursos_visibles_de_nave_en_periodo(nave, periodo).order_by(
        "recurso__nombre"
    )
    fichas_por_recurso_id = {
        ficha.recurso_id: ficha
        for ficha in FichaRegistro.objects.filter(
            periodo=periodo,
            recurso_id__in=matrices.values_list("recurso_id", flat=True),
        ).select_related("usuario", "modificado_por")
    }

    recursos_lista = []
    for matriz in matrices:
        ficha = fichas_por_recurso_id.get(matriz.recurso_id)
        payload_actual = MotorFichas.normalizar_payload_checklist(
            ficha.payload_checklist if ficha else {}
        )
        checklist_items = []
        for index, requerimiento in enumerate(matriz.recurso.requerimientos or []):
            checklist_items.append(
                {
                    "index": index,
                    "nombre": requerimiento,
                    "checked": payload_actual.get(requerimiento, {}).get("cumple", False),
                    "observacion": payload_actual.get(requerimiento, {}).get("observacion", ""),
                }
            )

        item = {
            "matriz": matriz,
            "recurso": matriz.recurso,
            "ficha": ficha,
            "tiene_ficha": ficha is not None,
            "estado_operativo": ficha.estado_operativo if ficha else None,
            "observacion_general": ficha.observacion_general if ficha else "",
            "checklist_items": checklist_items,
        }
        if slug is not None:
            item["action_url"] = (
                f"/{slug}/kiosco/periodos/{periodo.id}/recursos/{matriz.recurso.id}/ficha/"
            )
        recursos_lista.append(item)

    return recursos_lista


def _extraer_payload_ficha_desde_json(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, _json_error("JSON inválido.", 400)

    if not isinstance(payload, dict):
        return None, _json_error("El body debe ser un objeto JSON.", 400)

    estado_operativo = payload.get("estado_operativo")
    observacion_general = payload.get("observacion_general", "")
    payload_checklist = payload.get("payload_checklist", {})

    if estado_operativo is not None and type(estado_operativo) is not bool:
        return None, _json_error("estado_operativo debe ser booleano o null.", 400)
    if not isinstance(observacion_general, str):
        return None, _json_error("observacion_general debe ser texto.", 400)
    if not isinstance(payload_checklist, dict):
        return None, _json_error("payload_checklist debe ser un objeto JSON.", 400)

    return {
        "estado_operativo": estado_operativo,
        "observacion_general": observacion_general,
        "payload_checklist": payload_checklist,
    }, None


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan", "tierra")
def dashboard_tierra(request, slug):
    total_usuarios = TenantQueryService.get_usuarios_del_tenant(request.naviera).count()
    total_dispositivos = Dispositivo.objects.filter(naviera=request.naviera, is_active=True).count()
    fichas_hoy_total = FichaRegistro.objects.filter(
        periodo__nave__naviera=request.naviera,
        fecha_revision__date=timezone.localdate(),
    ).count()
    fallos_activos_total = FichaRegistro.objects.filter(
        periodo__nave__naviera=request.naviera,
        periodo__estado__in=TenantQueryService.ESTADOS_ABIERTOS,
        estado_operativo=False,
    ).count()
    naves_capitan = Nave.objects.none()
    if request.user.rol == "capitan":
        naves_capitan = (
            Nave.objects.filter(
                naviera=request.naviera,
                is_active=True,
                tripulantes__usuario=request.user,
            )
            .distinct()
            .order_by("nombre")
        )

    query_busqueda = request.GET.get("q", "").strip()
    naves_activas = TenantQueryService.get_naves_activas(request.naviera).annotate(
        periodos_abiertos=Count(
            "periodos",
            filter=Q(periodos__estado__in=TenantQueryService.ESTADOS_ABIERTOS),
            distinct=True,
        ),
        ultimo_registro=Greatest(
            Max("periodos__fichas__fecha_revision"),
            Coalesce(
                Max("periodos__fichas__modificado_en"),
                Max("periodos__fichas__fecha_revision"),
            ),
        ),
        fallos_activos=Count(
            "periodos__fichas",
            filter=Q(
                periodos__estado__in=TenantQueryService.ESTADOS_ABIERTOS,
                periodos__fichas__estado_operativo=False,
            ),
            distinct=True,
        ),
        fichas_hoy=Count(
            "periodos__fichas",
            filter=Q(periodos__fichas__fecha_revision__date=timezone.localdate()),
            distinct=True,
        ),
    )

    if query_busqueda:
        naves_activas = naves_activas.filter(
            Q(nombre__icontains=query_busqueda) | Q(matricula__icontains=query_busqueda)
        )

    paginator = Paginator(naves_activas.order_by("nombre"), 10)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    ultimas_fichas = (
        FichaRegistro.objects.filter(
            periodo__nave__naviera=request.naviera,
        )
        .select_related(
            "recurso",
            "usuario",
            "periodo__nave",
            "periodo__periodicidad",
        )
        .order_by("-fecha_revision")[:10]
    )

    return render(
        request,
        "inventory/dashboard_tierra.html",
        {
            "page_obj": page_obj,
            "query_busqueda": query_busqueda,
            "ultimas_fichas": ultimas_fichas,
            "total_usuarios": total_usuarios,
            "total_dispositivos": total_dispositivos,
            "fichas_hoy_total": fichas_hoy_total,
            "fallos_activos_total": fallos_activos_total,
            "naves_capitan": naves_capitan,
            "slug": slug,
            "naviera": request.naviera,
            "usuarios_url": f"/{slug}/usuarios/",
            "naves_url": f"/{slug}/naves/",
            "dispositivos_url": f"/{slug}/kiosco/hardware/",
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan", "tierra")
def nave_detalle(request, slug, nave_id):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    filtros_historial = _obtener_filtros_historial_desde_request(request)
    periodos_abiertos = TenantQueryService.get_periodos_abiertos_de_nave(nave).order_by("-fecha_inicio")
    historial = TenantQueryService.get_periodos_historial_de_nave(
        nave,
        fecha_desde=filtros_historial["fecha_desde"],
        fecha_hasta=filtros_historial["fecha_hasta"],
        estado=filtros_historial["estado_filtro"] or None,
        periodicidad_id=filtros_historial["periodicidad_id_filtro"] or None,
    )
    periodicidades = Periodicidad.objects.all().order_by("nombre")
    periodos_abiertos_detalle = _construir_periodos_detalle(nave, periodos_abiertos)
    historial_detalle = _construir_periodos_detalle(nave, historial)
    fallos_activos_nave = sum(item["fallos_count"] for item in periodos_abiertos_detalle)
    total_recursos_nave = sum(item["total_recursos"] for item in periodos_abiertos_detalle)

    es_admin = request.user.rol in {"admin_sitrep", "admin_naviera", "capitan"}

    return render(
        request,
        "inventory/nave_detalle.html",
        {
            "nave": nave,
            "periodos_abiertos_detalle": periodos_abiertos_detalle,
            "historial_detalle": historial_detalle,
            "periodicidades": periodicidades,
            "fallos_activos_nave": fallos_activos_nave,
            "total_recursos_nave": total_recursos_nave,
            "slug": slug,
            "es_admin": es_admin,
            "fecha_desde_str": filtros_historial["fecha_desde_str"],
            "fecha_hasta_str": filtros_historial["fecha_hasta_str"],
            "estado_filtro": filtros_historial["estado_filtro"],
            "periodicidad_id_filtro": filtros_historial["periodicidad_id_filtro"],
        },
    )


@tenant_member_required
@requiere_rol("mar", "capitan", "tierra", "admin_naviera", "admin_sitrep")
def dashboard_kiosco(request, slug):
    nave_id = request.session.get("nave_id")
    if not nave_id:
        return redirect(f"/{slug}/kiosco/login/")

    try:
        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    except Http404:
        return redirect(f"/{slug}/kiosco/login/")

    filtros_historial = _obtener_filtros_historial_desde_request(request)

    periodos_abiertos = list(
        TenantQueryService.get_periodos_abiertos_de_nave(nave).order_by("fecha_inicio", "id")
    )
    historial = list(
        TenantQueryService.get_periodos_historial_de_nave(
            nave,
            fecha_desde=filtros_historial["fecha_desde"],
            fecha_hasta=filtros_historial["fecha_hasta"],
            estado=filtros_historial["estado_filtro"] or None,
            periodicidad_id=filtros_historial["periodicidad_id_filtro"] or None,
        )
    )
    periodicidades = Periodicidad.objects.all().order_by("nombre")
    fichas_completadas_por_periodo = _contar_fichas_completas_por_periodo(
        [periodo.id for periodo in periodos_abiertos]
    )
    fichas_completadas_count = _contar_fichas_completas_por_periodo([periodo.id for periodo in historial])

    periodos_resumen = []
    # TODO: optimizar con annotate() en Fase 4
    for periodo in periodos_abiertos:
        total_recursos = MatrizNaveRecurso.objects.filter(
            nave=nave,
            es_visible=True,
            recurso__periodicidad_id=periodo.periodicidad_id,
        ).count()
        fichas_completadas = fichas_completadas_por_periodo.get(periodo.id, 0)
        periodos_resumen.append(
            {
                "periodo": periodo,
                "total_recursos": total_recursos,
                "fichas_completadas": fichas_completadas,
                "completado": fichas_completadas >= total_recursos,
            }
        )
    for periodo in historial:
        periodo.fichas_completadas_count = fichas_completadas_count.get(periodo.id, 0)

    return render(
        request,
        "inventory/kiosco_dashboard.html",
        {
            "nave": nave,
            "periodos_resumen": periodos_resumen,
            "historial": historial,
            "periodicidades": periodicidades,
            "fecha_desde_str": filtros_historial["fecha_desde_str"],
            "fecha_hasta_str": filtros_historial["fecha_hasta_str"],
            "estado_filtro": filtros_historial["estado_filtro"],
            "periodicidad_id_filtro": filtros_historial["periodicidad_id_filtro"],
            "fichas_completadas_count": fichas_completadas_count,
            "slug": slug,
            "usuario": request.user,
        },
    )


@tenant_member_required
@requiere_rol("mar", "capitan", "tierra", "admin_naviera", "admin_sitrep")
def kiosco_periodo_detalle(request, slug, periodo_id):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    nave_id = request.session.get("nave_id")
    if not nave_id:
        logger.info(
            "kiosco_periodo_detalle redirect login: session without nave_id (user_id=%s, naviera_id=%s)",
            getattr(request.user, "id", None),
            getattr(request.naviera, "id", None),
        )
        return redirect(f"/{slug}/kiosco/login/")

    try:
        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    except Http404:
        logger.info(
            "kiosco_periodo_detalle redirect login: nave not found/active (nave_id=%s, naviera_id=%s)",
            nave_id,
            getattr(request.naviera, "id", None),
        )
        return redirect(f"/{slug}/kiosco/login/")

    try:
        periodo = PeriodoRevision.objects.select_related("periodicidad").get(
            id=periodo_id,
            nave=nave,
            estado__in=TenantQueryService.ESTADOS_ABIERTOS,
        )
    except PeriodoRevision.DoesNotExist:
        logger.info(
            "kiosco_periodo_detalle redirect dashboard: periodo not found/open (periodo_id=%s, nave_id=%s)",
            periodo_id,
            nave.id,
        )
        return redirect(f"/{slug}/kiosco/")

    error_recurso_id = request.GET.get("error_recurso")
    error_msg = request.GET.get("error_msg", "")
    try:
        error_recurso_id = int(error_recurso_id) if error_recurso_id else None
    except (TypeError, ValueError):
        error_recurso_id = None

    recursos_lista = _construir_recursos_lista_periodo(nave, periodo, slug=slug)
    fichas_completadas_count = sum(1 for item in recursos_lista if item["tiene_ficha"])

    return render(
        request,
        "inventory/kiosco_periodo_detalle.html",
        {
            "nave": nave,
            "periodo": periodo,
            "recursos_lista": recursos_lista,
            "fichas_completadas_count": fichas_completadas_count,
            "error_recurso_id": error_recurso_id,
            "error_msg": error_msg,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_rol("mar", "capitan", "tierra", "admin_naviera", "admin_sitrep")
def kiosco_periodo_historial(request, slug, periodo_id):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    nave_id = request.session.get("nave_id")
    if not nave_id:
        logger.info(
            "kiosco_periodo_historial redirect login: session without nave_id (user_id=%s, naviera_id=%s)",
            getattr(request.user, "id", None),
            getattr(request.naviera, "id", None),
        )
        return redirect(f"/{slug}/kiosco/login/")

    try:
        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    except Http404:
        logger.info(
            "kiosco_periodo_historial redirect login: nave not found/active (nave_id=%s, naviera_id=%s)",
            nave_id,
            getattr(request.naviera, "id", None),
        )
        return redirect(f"/{slug}/kiosco/login/")

    ESTADOS_CERRADOS = {"conforme", "observado", "fallido", "omitido", "caduco"}
    try:
        periodo = PeriodoRevision.objects.select_related("periodicidad").get(
            id=periodo_id,
            nave=nave,
            estado__in=ESTADOS_CERRADOS,
        )
    except PeriodoRevision.DoesNotExist:
        logger.info(
            "kiosco_periodo_historial redirect dashboard: periodo not found/closed (periodo_id=%s, nave_id=%s)",
            periodo_id,
            nave.id,
        )
        return redirect(f"/{slug}/kiosco/")

    recursos_lista = _construir_recursos_lista_periodo(nave, periodo)

    return render(
        request,
        "inventory/kiosco_periodo_historial.html",
        {
            "nave": nave,
            "periodo": periodo,
            "recursos_lista": recursos_lista,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_rol("mar", "capitan", "tierra", "admin_naviera", "admin_sitrep")
def kiosco_recurso_ficha(request, slug, periodo_id, recurso_id):
    if request.method not in ["GET", "POST"]:
        return HttpResponseNotAllowed(["GET", "POST"])

    nave_id = request.session.get("nave_id")
    if not nave_id:
        logger.info(
            "kiosco_recurso_ficha redirect login: session without nave_id (user_id=%s, naviera_id=%s)",
            getattr(request.user, "id", None),
            getattr(request.naviera, "id", None),
        )
        return redirect(f"/{slug}/kiosco/login/")

    try:
        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    except Http404:
        logger.info(
            "kiosco_recurso_ficha redirect login: nave not found/active (nave_id=%s, naviera_id=%s)",
            nave_id,
            getattr(request.naviera, "id", None),
        )
        return redirect(f"/{slug}/kiosco/login/")

    try:
        periodo = PeriodoRevision.objects.select_related("periodicidad").get(
            id=periodo_id,
            nave=nave,
            estado__in=TenantQueryService.ESTADOS_ABIERTOS,
        )
    except PeriodoRevision.DoesNotExist:
        logger.info(
            "kiosco_recurso_ficha redirect dashboard: periodo not found/open (periodo_id=%s, nave_id=%s)",
            periodo_id,
            nave.id,
        )
        return redirect(f"/{slug}/kiosco/")

    try:
        matriz = MatrizNaveRecurso.objects.select_related(
            "recurso",
            "recurso__proposito",
        ).get(
            nave=nave,
            recurso_id=recurso_id,
            es_visible=True,
            recurso__periodicidad_id=periodo.periodicidad_id,
        )
    except MatrizNaveRecurso.DoesNotExist:
        logger.info(
            "kiosco_recurso_ficha redirect detalle: matriz visible not found (periodo_id=%s, recurso_id=%s, nave_id=%s)",
            periodo.id,
            recurso_id,
            nave.id,
        )
        return redirect(f"/{slug}/kiosco/periodos/{periodo.id}/")

    recurso = matriz.recurso
    requerimientos = recurso.requerimientos or []
    ficha = TenantQueryService.get_ficha_de_periodo_y_recurso(periodo, recurso)
    tiene_ficha = ficha is not None

    estado_operativo_form = ficha.estado_operativo if ficha else False
    observacion_general_form = ficha.observacion_general if ficha else ""
    payload_checklist_form = MotorFichas.normalizar_payload_checklist(
        ficha.payload_checklist if ficha else {}
    )

    if request.method == "POST":
        estado_operativo_form = request.POST.get("estado_operativo") == "on"
        observacion_general_form = (request.POST.get("observacion_general") or "").strip()
        payload_checklist_form = {}
        for index, requerimiento in enumerate(requerimientos):
            payload_checklist_form[requerimiento] = {
                "cumple": request.POST.get(f"req_{index}") == "on",
                "observacion": (request.POST.get(f"obs_{index}") or "").strip(),
            }
        if estado_operativo_form is True:
            hay_fallo = any(
                not valor.get("cumple", True)
                for valor in payload_checklist_form.values()
                if isinstance(valor, dict)
            )
            if hay_fallo:
                estado_operativo_form = False

        try:
            if tiene_ficha:
                ficha = MotorFichas.modificar_ficha(
                    ficha=ficha,
                    usuario_modificador=request.user,
                    estado_operativo=estado_operativo_form,
                    observacion_general=observacion_general_form,
                    payload_checklist=payload_checklist_form,
                )
            else:
                ficha = MotorFichas.crear_ficha(
                    periodo=periodo,
                    recurso=recurso,
                    usuario=request.user,
                    estado_operativo=estado_operativo_form,
                    observacion_general=observacion_general_form,
                    payload_checklist=payload_checklist_form,
                )
            logger.info(
                "kiosco_recurso_ficha saved (ficha_id=%s, periodo_id=%s, recurso_id=%s, user_id=%s)",
                ficha.id,
                periodo.id,
                recurso.id,
                request.user.id,
            )
            return redirect(f"/{slug}/kiosco/periodos/{periodo.id}/")
        except ValueError as exc:
            error_query = urlencode(
                {
                    "error_recurso": recurso.id,
                    "error_msg": str(exc),
                }
            )
            return redirect(f"/{slug}/kiosco/periodos/{periodo.id}/?{error_query}")
    else:
        error = None

    checklist_items = [
        {
            "index": index,
            "nombre": requerimiento,
            "checked": payload_checklist_form.get(requerimiento, {}).get("cumple", False),
            "observacion": payload_checklist_form.get(requerimiento, {}).get("observacion", ""),
        }
        for index, requerimiento in enumerate(requerimientos)
    ]

    return render(
        request,
        "inventory/kiosco_recurso_ficha.html",
        {
            "nave": nave,
            "periodo": periodo,
            "matriz": matriz,
            "recurso": recurso,
            "ficha": ficha,
            "tiene_ficha": tiene_ficha,
            "slug": slug,
            "error": error,
            "estado_operativo_form": estado_operativo_form,
            "observacion_general_form": observacion_general_form,
            "checklist_items": checklist_items,
        },
    )


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


def redirect_kiosco_login(request, slug):
    return redirect(f"/{slug}/login/?modo=mar")


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
                return _render_login_unificado(
                    request,
                    slug,
                    modo,
                    limpiar_token=True,
                )

            return _render_login_unificado(
                request,
                slug,
                modo,
                error="Acceso denegado.",
            )

        email = request.POST.get("email")
        password = request.POST.get("password")

        usuario = authenticate(request, email=email, password=password)
        if usuario is not None:
            login(request, usuario)
            return redirect(f"/{slug}/")

        return _render_login_unificado(
            request,
            slug,
            modo,
            error="Credenciales inválidas.",
        )

    return _render_login_unificado(request, slug, modo)


def logout_kiosco(request, slug):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    logout(request)
    request.session.flush()
    return redirect(f"/{slug}/login/?modo=mar")  # ← antes era /{slug}/kiosco/login/


def redirect_kiosco_login(request, slug):
    return redirect(f"/{slug}/login/?modo=mar")


@tenant_member_required
def logout_tierra(request, slug):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    logout(request)
    return redirect("inventory:login_tierra", slug=slug)


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def setup_kiosco(request, slug):
    # 2. PROCESAMIENTO DEL PAYLOAD (POST)
    if request.method == "POST":
        nombre_dispositivo = request.POST.get("nombre_dispositivo")
        nave_id = request.POST.get("nave_id")

        if not nave_id:
            return HttpResponseForbidden("Debe asignar el dispositivo a una nave.")

        # Validación de Jurisdicción (Previene IDOR)
        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)

        # Fabricación del Hardware Binding
        dispositivo = Dispositivo(naviera=request.naviera, nave=nave, nombre=nombre_dispositivo)
        token_plano = dispositivo.generar_nuevo_token()
        dispositivo.save()

        # Renderizamos la vista de éxito inyectando el token secreto
        contexto = {"token_plano": token_plano, "dispositivo": dispositivo}
        return render(request, "inventory/kiosco_tatuado.html", contexto)

    # 3. RENDERIZADO DEL FORMULARIO (GET)
    naves = TenantQueryService.get_naves_activas(request.naviera)
    return render(request, "inventory/kiosco_setup.html", {"naves": naves})


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def listar_dispositivos(request, slug):
    dispositivos = TenantQueryService.get_dispositivos(request.naviera).order_by("nave__nombre", "nombre")

    contexto = {
        "dispositivos": dispositivos,
        "slug": slug,
    }
    return render(request, "inventory/dispositivos_lista.html", contexto)


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def revocar_dispositivo(request, slug, id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    dispositivo = TenantQueryService.get_dispositivo(request.naviera, id)

    if not dispositivo.is_active:
        return redirect(f"/{slug}/kiosco/hardware/")

    dispositivo.is_active = False
    dispositivo.save(update_fields=["is_active"])

    return redirect(f"/{slug}/kiosco/hardware/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def listar_naves(request, slug):
    naves = TenantQueryService.get_naves_activas(request.naviera).annotate(
        periodos_abiertos=Count(
            "periodos",
            filter=Q(periodos__estado__in=TenantQueryService.ESTADOS_ABIERTOS),
            distinct=True,
        ),
        fallos_activos=Count(
            "periodos__fichas",
            filter=Q(
                periodos__estado__in=TenantQueryService.ESTADOS_ABIERTOS,
                periodos__fichas__estado_operativo=False,
            ),
            distinct=True,
        ),
    )
    return render(
        request,
        "inventory/naves_lista.html",
        {
            "naves": naves.order_by("nombre"),
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def crear_nave(request, slug):
    if request.method == "GET":
        return render(
            request,
            "inventory/nave_form.html",
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

    if Nave.objects.filter(naviera=request.naviera, matricula=matricula, is_active=True).exists():
        return render(
            request,
            "inventory/nave_form.html",
            {
                "error": "La matrícula ya existe en esta naviera.",
                "slug": slug,
                "form_data": form_data,
            },
        )

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
            "inventory/nave_form.html",
            {
                "error": "La matrícula ya existe en esta naviera.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    return redirect(f"/{slug}/naves/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def editar_nave(request, slug, nave_id):
    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)

    if request.method == "GET":
        return render(
            request,
            "inventory/nave_form.html",
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
            "inventory/nave_form.html",
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
@requiere_rol("admin_sitrep", "admin_naviera")
def desactivar_nave(request, slug, nave_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    nave = TenantQueryService.get_nave(request.naviera, nave_id)
    if not nave.is_active:
        return redirect(f"/{slug}/naves/")

    nave.delete()
    return redirect(f"/{slug}/naves/")


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


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def listar_tripulacion(request, slug, nave_id):
    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    tripulacion = TenantQueryService.get_tripulacion_activa_de_nave(request.naviera, nave_id)
    usuarios_asignados_ids = tripulacion.values_list("usuario_id", flat=True)
    usuarios_disponibles = TenantQueryService.get_usuarios_del_tenant(request.naviera).exclude(
        id__in=usuarios_asignados_ids
    )

    return render(
        request,
        "inventory/tripulacion_lista.html",
        {
            "nave": nave,
            "tripulacion": tripulacion,
            "usuarios_disponibles": usuarios_disponibles,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def agregar_tripulante(request, slug, nave_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    usuario_id = request.POST.get("usuario_id")
    usuario = TenantQueryService.get_usuario_activo_del_tenant(request.naviera, usuario_id)

    try:
        Tripulacion.objects.create(usuario=usuario, nave=nave)
    except IntegrityError:
        pass

    return redirect(f"/{slug}/naves/{nave_id}/tripulacion/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def remover_tripulante(request, slug, nave_id, tripulacion_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)

    try:
        tripulacion = Tripulacion.objects.get(id=tripulacion_id, nave=nave)
    except Tripulacion.DoesNotExist as exc:
        raise Http404("Recurso no encontrado.") from exc

    tripulacion.delete()
    return redirect(f"/{slug}/naves/{nave_id}/tripulacion/")


@tenant_member_required
def api_periodos_nave(request, slug):
    if request.method != "GET":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodos = list(TenantQueryService.get_periodos_abiertos_de_nave(nave).order_by("fecha_inicio", "id"))
    periodicidad_ids = [periodo.periodicidad_id for periodo in periodos]
    periodo_ids = [periodo.id for periodo in periodos]

    recursos_por_periodicidad = {}
    if periodicidad_ids:
        recursos_por_periodicidad = {
            row["recurso__periodicidad_id"]: row["total"]
            for row in (
                MatrizNaveRecurso.objects.filter(
                    nave=nave,
                    es_visible=True,
                    recurso__periodicidad_id__in=periodicidad_ids,
                )
                .values("recurso__periodicidad_id")
                .annotate(total=Count("id"))
            )
        }

    fichas_por_periodo = _contar_fichas_completas_por_periodo(periodo_ids)

    payload = {
        "nave": {
            "id": nave.id,
            "nombre": nave.nombre,
            "matricula": nave.matricula,
        },
        "periodos": [
            {
                "id": periodo.id,
                "periodicidad": periodo.periodicidad.nombre,
                "fecha_inicio": periodo.fecha_inicio.isoformat(),
                "fecha_termino": periodo.fecha_termino.isoformat(),
                "estado": periodo.get_estado_display(),
                "total_recursos": recursos_por_periodicidad.get(periodo.periodicidad_id, 0),
                "fichas_completadas": fichas_por_periodo.get(periodo.id, 0),
            }
            for periodo in periodos
        ],
    }
    return JsonResponse(payload, status=200)


@tenant_member_required
def api_recursos_periodo(request, slug, periodo_id):
    if request.method != "GET":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = _obtener_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    recursos = []
    matrices = TenantQueryService.get_recursos_visibles_de_nave_en_periodo(nave, periodo).order_by(
        "recurso__nombre",
        "id",
    )
    for matriz in matrices:
        ficha = TenantQueryService.get_ficha_de_periodo_y_recurso(periodo, matriz.recurso)
        recursos.append(
            {
                "matriz_id": matriz.id,
                "recurso_id": matriz.recurso_id,
                "nombre": matriz.recurso.nombre,
                "tipo": matriz.recurso.proposito.tipo,
                "categoria": matriz.recurso.proposito.categoria,
                "cantidad": matriz.cantidad,
                "requerimientos": matriz.recurso.requerimientos or [],
                "tiene_ficha": ficha is not None,
                "estado_operativo": ficha.estado_operativo if ficha else None,
                "observacion_general": ficha.observacion_general if ficha else "",
            }
        )

    payload = {
        "periodo": {
            "id": periodo.id,
            "periodicidad": periodo.periodicidad.nombre,
            "fecha_inicio": periodo.fecha_inicio.isoformat(),
            "fecha_termino": periodo.fecha_termino.isoformat(),
        },
        "recursos": recursos,
    }
    return JsonResponse(payload, status=200)


@tenant_member_required
def api_detalle_recurso(request, slug, periodo_id, recurso_id):
    if request.method != "GET":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = _obtener_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    try:
        matriz = MatrizNaveRecurso.objects.select_related(
            "recurso",
            "recurso__proposito",
            "recurso__periodicidad",
        ).get(
            nave=nave,
            recurso_id=recurso_id,
            es_visible=True,
            recurso__periodicidad_id=periodo.periodicidad_id,
        )
    except MatrizNaveRecurso.DoesNotExist:
        return _json_error("Recurso no encontrado en la matriz visible de la nave.", 404)

    ficha = TenantQueryService.get_ficha_de_periodo_y_recurso(periodo, matriz.recurso)
    usuario_ficha = None
    estado_operativo = None
    observacion_general = ""
    payload_checklist = {}
    fecha_revision = None

    if ficha:
        estado_operativo = ficha.estado_operativo
        observacion_general = ficha.observacion_general
        payload_checklist = MotorFichas.normalizar_payload_checklist(ficha.payload_checklist or {})
        fecha_revision = ficha.fecha_revision.isoformat() if ficha.fecha_revision else None

        nombre_completo = f"{ficha.usuario.first_name} {ficha.usuario.last_name}".strip()
        if not nombre_completo:
            nombre_completo = ficha.usuario.rut
        usuario_ficha = f"{nombre_completo} ({ficha.usuario.rut})"

    payload = {
        "recurso": {
            "id": matriz.recurso.id,
            "nombre": matriz.recurso.nombre,
            "tipo": matriz.recurso.proposito.tipo,
            "categoria": matriz.recurso.proposito.categoria,
            "cantidad_requerida": matriz.cantidad,
            "requerimientos": matriz.recurso.requerimientos or [],
        },
        "ficha": {
            "existe": ficha is not None,
            "estado_operativo": estado_operativo,
            "observacion_general": observacion_general,
            "payload_checklist": payload_checklist,
            "fecha_revision": fecha_revision,
            "usuario": usuario_ficha,
        },
    }
    return JsonResponse(payload, status=200)


@tenant_member_required
def api_crear_ficha(request, slug, periodo_id, recurso_id):
    if request.method != "POST":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = _obtener_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    try:
        recurso = Recurso.objects.get(id=recurso_id)
    except Recurso.DoesNotExist:
        return _json_error("Recurso no encontrado.", 404)

    data, error = _extraer_payload_ficha_desde_json(request)
    if error:
        return error

    try:
        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=request.user,
            estado_operativo=data["estado_operativo"],
            observacion_general=data["observacion_general"],
            payload_checklist=data["payload_checklist"],
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    return JsonResponse({"id": ficha.id, "created": True}, status=201)


@tenant_member_required
def api_modificar_ficha(request, slug, periodo_id, recurso_id):
    if request.method != "PATCH":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = _obtener_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    try:
        ficha = FichaRegistro.objects.get(periodo=periodo, recurso_id=recurso_id)
    except FichaRegistro.DoesNotExist:
        return _json_error("Ficha no encontrada para este recurso y período.", 404)

    data, error = _extraer_payload_ficha_desde_json(request)
    if error:
        return error

    try:
        ficha = MotorFichas.modificar_ficha(
            ficha=ficha,
            usuario_modificador=request.user,
            estado_operativo=data["estado_operativo"],
            observacion_general=data["observacion_general"],
            payload_checklist=data["payload_checklist"],
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    return JsonResponse({"id": ficha.id, "modified": True}, status=200)
