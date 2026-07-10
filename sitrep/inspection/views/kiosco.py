import logging
from urllib.parse import urlencode

from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone

from sitrep.accounts.audit import registrar_acceso
from sitrep.accounts.decorators import requiere_rol, tenant_member_required
from sitrep.catalog.models import Periodicidad

from ..models import MatrizNaveRecurso, PeriodoRevision
from .. import presenters, repositories
from ..services import TenantQueryService, MotorFichas, contar_fichas_completas_por_periodo
from .tierra import _obtener_filtros_historial_desde_request

logger = logging.getLogger(__name__)


def _get_nave_kiosco_o_redirect(request, slug):
    nave_id = request.session.get("nave_id")
    if not nave_id:
        logger.info(
            "kiosco redirect login: no nave_id in session (user_id=%s, naviera_id=%s)",
            request.user.id,
            request.naviera.id,
        )
        return None, redirect(f"/{slug}/kiosco/login/")
    try:
        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    except Http404:
        logger.info(
            "kiosco redirect login: nave not found/active (nave_id=%s, naviera_id=%s)",
            nave_id,
            request.naviera.id,
        )
        return None, redirect(f"/{slug}/kiosco/login/")
    return nave, None


def _parse_estado_checklist_form(raw_estado):
    if raw_estado == "on":
        return True
    if raw_estado == "off":
        return False
    return None


@tenant_member_required
@requiere_rol("mar", "capitan", "tierra", "admin_naviera", "admin_sitrep")
def dashboard_kiosco(request, slug):
    nave, redir = _get_nave_kiosco_o_redirect(request, slug)
    if redir:
        return redir

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
    fichas_completadas_por_periodo = contar_fichas_completas_por_periodo(
        [periodo.id for periodo in periodos_abiertos]
    )
    fichas_completadas_count = contar_fichas_completas_por_periodo([periodo.id for periodo in historial])

    periodos_resumen = []
    hoy = timezone.localdate()
    # TODO: optimizar con annotate() en Fase 4
    for periodo in periodos_abiertos:
        numero_periodo = presenters.numero_periodo(periodo, nave)
        total_recursos = MatrizNaveRecurso.objects.filter(
            nave=nave,
            es_visible=True,
            recurso__periodicidad_id=periodo.periodicidad_id,
        ).count()
        fichas_completadas = fichas_completadas_por_periodo.get(periodo.id, 0)
        periodos_resumen.append(
            {
                "periodo": periodo,
                "numero": numero_periodo,
                "numero_label": presenters.etiqueta_numero_periodicidad(periodo.periodicidad),
                "total_recursos": total_recursos,
                "fichas_completadas": fichas_completadas,
                "completado": fichas_completadas >= total_recursos,
                "dias_restantes": max(0, (periodo.fecha_termino - hoy).days),
            }
        )
    for periodo in historial:
        periodo.fichas_completadas_count = fichas_completadas_count.get(periodo.id, 0)
        periodo.numero_periodo = presenters.numero_periodo(periodo, nave)
        periodo.numero_periodo_label = presenters.etiqueta_numero_periodicidad(periodo.periodicidad)

    return render(
        request,
        "inspection/kiosco/kiosco_dashboard.html",
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

    nave, redir = _get_nave_kiosco_o_redirect(request, slug)
    if redir:
        return redir

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

    recursos_lista = presenters.construir_recursos_lista_periodo(nave, periodo, slug=slug)
    datos_anterior = repositories.get_datos_periodo_anterior(nave, periodo)
    for item in recursos_lista:
        ficha_anterior = datos_anterior.get(item["recurso"].id)
        item["periodo_anterior_json"] = presenters.construir_periodo_anterior_json(
            ficha_anterior, item["checklist_items"]
        )

    areas_grupos = presenters.agrupar_recursos_por_area(recursos_lista)
    fichas_completadas_count = sum(1 for item in recursos_lista if item["ficha_completa"])
    numero_periodo = presenters.numero_periodo(periodo, nave)

    return render(
        request,
        "inspection/kiosco/kiosco_periodo_detalle.html",
        {
            "nave": nave,
            "periodo": periodo,
            "numero_periodo": numero_periodo,
            "numero_periodo_label": presenters.etiqueta_numero_periodicidad(periodo.periodicidad),
            "recursos_lista": recursos_lista,
            "areas_grupos": areas_grupos,
            "fichas_completadas_count": fichas_completadas_count,
            "error_recurso_id": error_recurso_id,
            "error_msg": error_msg,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_rol("mar", "capitan", "tierra", "admin_naviera", "admin_sitrep")
def kiosco_periodo_pdf(request, slug, periodo_id):
    import io
    from weasyprint import HTML

    nave, redir = _get_nave_kiosco_o_redirect(request, slug)
    if redir:
        return redir

    try:
        periodo = PeriodoRevision.objects.select_related("periodicidad").get(
            id=periodo_id,
            nave=nave,
            estado__in=TenantQueryService.ESTADOS_ABIERTOS,
        )
    except PeriodoRevision.DoesNotExist:
        return redirect(f"/{slug}/kiosco/")

    recursos_lista = presenters.construir_recursos_lista_periodo(nave, periodo, slug=slug)
    areas_grupos = presenters.agrupar_recursos_por_area(recursos_lista)

    presenters.adjuntar_colores_pdf(areas_grupos)

    html_string = render_to_string(
        "inspection/kiosco/ficha_pdf.html",
        {
            "nave": nave,
            "periodo": periodo,
            "areas_grupos": areas_grupos,
            "naviera": request.naviera,
        },
        request=request,
    )

    pdf_file = io.BytesIO()
    HTML(string=html_string, base_url=request.build_absolute_uri("/")).write_pdf(pdf_file)
    pdf_file.seek(0)

    nombre_archivo = f"ficha_{nave.matricula}_{periodo.periodicidad.nombre}_{periodo.fecha_inicio}.pdf"
    registrar_acceso(
        request, "export", "ficha_pdf",
        detalle=f"nave={nave.matricula} periodo_id={periodo.id}",
    )
    response = HttpResponse(pdf_file.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{nombre_archivo}"'
    return response


@tenant_member_required
@requiere_rol("mar", "capitan", "tierra", "admin_naviera", "admin_sitrep")
def kiosco_periodo_historial(request, slug, periodo_id):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    nave, redir = _get_nave_kiosco_o_redirect(request, slug)
    if redir:
        return redir

    try:
        periodo = PeriodoRevision.objects.select_related("periodicidad").get(
            id=periodo_id,
            nave=nave,
            estado__in=TenantQueryService.ESTADOS_CERRADOS,
        )
    except PeriodoRevision.DoesNotExist:
        logger.info(
            "kiosco_periodo_historial redirect dashboard: periodo not found/closed (periodo_id=%s, nave_id=%s)",
            periodo_id,
            nave.id,
        )
        return redirect(f"/{slug}/kiosco/")

    recursos_lista = presenters.construir_recursos_lista_periodo(nave, periodo, for_history=True)
    areas_grupos = presenters.agrupar_recursos_por_area(recursos_lista)

    return render(
        request,
        "inspection/kiosco/kiosco_periodo_historial.html",
        {
            "nave": nave,
            "periodo": periodo,
            "numero_periodo": presenters.numero_periodo(periodo, nave),
            "numero_periodo_label": presenters.etiqueta_numero_periodicidad(periodo.periodicidad),
            "areas_grupos": areas_grupos,
            "recursos_lista": recursos_lista,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_rol("mar", "capitan", "tierra", "admin_naviera", "admin_sitrep")
def kiosco_recurso_ficha(request, slug, periodo_id, recurso_id):
    if request.method not in ["GET", "POST"]:
        return HttpResponseNotAllowed(["GET", "POST"])

    nave, redir = _get_nave_kiosco_o_redirect(request, slug)
    if redir:
        return redir

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
        checklist_definicion = MotorFichas.construir_checklist_items(
            recurso=recurso,
            cantidad=matriz.cantidad,
            payload_checklist=payload_checklist_form,
        )
        for item in checklist_definicion:
            estado_item = _parse_estado_checklist_form(request.POST.get(f"req_{item['index']}"))
            if estado_item is None:
                continue
            payload_checklist_form[item["key"]] = {
                "cumple": estado_item,
                "observacion": (request.POST.get(f"obs_{item['index']}") or "").strip(),
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

    checklist_items = MotorFichas.construir_checklist_items(
        recurso=recurso,
        cantidad=matriz.cantidad,
        payload_checklist=payload_checklist_form,
    )
    datos_anterior = repositories.get_datos_periodo_anterior(nave, periodo)
    ficha_anterior = datos_anterior.get(recurso.id)
    periodo_anterior_json = presenters.construir_periodo_anterior_json(ficha_anterior, checklist_items)

    return render(
        request,
        "inspection/kiosco/kiosco_recurso_ficha.html",
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
            "periodo_anterior_json": periodo_anterior_json,
        },
    )
