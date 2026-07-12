from datetime import date

from django.db.models import Count, F, IntegerField, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, Greatest
from django.http import HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.utils import timezone

from core.utils import paginate
from sitrep.accounts.decorators import requiere_rol, tenant_member_required
from sitrep.catalog.models import Area, Periodicidad
from sitrep.fleet.models import Dispositivo, Nave
from sitrep.fleet.services import FleetQueryService

from ..models import FichaRegistro, MatrizNaveRecurso, PeriodoRevision
from .. import presenters
from ..services import TenantQueryService
from .pdf import generar_pdf_periodo


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


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan", "tierra")
def dashboard_tierra(request, slug):
    naves_capitan = Nave.objects.none()
    if request.user.rol == "capitan":
        naves_capitan = FleetQueryService.get_naves_capitan(request.user, request.naviera)

    if request.user.rol == "capitan":
        from django.contrib.auth import get_user_model
        total_usuarios = get_user_model().objects.filter(
            asignaciones_naves__nave__in=naves_capitan
        ).distinct().count()
    else:
        total_usuarios = TenantQueryService.get_usuarios_del_tenant(request.naviera).count()

    dispositivos_qs = Dispositivo.objects.filter(naviera=request.naviera, is_active=True)
    if request.user.rol == "capitan":
        dispositivos_qs = dispositivos_qs.filter(nave__in=naves_capitan)
    total_dispositivos = dispositivos_qs.count()

    fichas_hoy_qs = FichaRegistro.objects.filter(
        periodo__nave__naviera=request.naviera,
        fecha_revision__date=timezone.localdate(),
    )
    if request.user.rol == "capitan":
        fichas_hoy_qs = fichas_hoy_qs.filter(periodo__nave__in=naves_capitan)
    fichas_hoy_total = fichas_hoy_qs.count()

    fallos_base_qs = MatrizNaveRecurso.objects.filter(
        nave__naviera=request.naviera,
        nave__is_active=True,
        es_visible=True,
    )
    if request.user.rol == "capitan":
        fallos_base_qs = fallos_base_qs.filter(nave__in=naves_capitan)
    fallos_activos_total = fallos_base_qs.filter(ultimo_estado_operativo=False).count()
    fallos_nuevos_total = fallos_base_qs.filter(es_fallo_nuevo=True).count()

    estados_vencidos = PeriodoRevision.ESTADOS_INCOMPLETOS
    periodos_cerrados_qs = PeriodoRevision.objects.filter(
        nave__naviera=request.naviera,
        nave__is_active=True,
        estado__in=TenantQueryService.ESTADOS_CERRADOS,
    )
    if request.user.rol == "capitan":
        periodos_cerrados_qs = periodos_cerrados_qs.filter(nave__in=naves_capitan)
    todos_periodos_cerrados = (
        periodos_cerrados_qs
        .order_by("nave_id", "periodicidad_id", "-fecha_inicio", "-id")
        .values("nave_id", "periodicidad_id", "estado")
    )
    ultimos_periodos_cerrados = {}
    for periodo in todos_periodos_cerrados:
        clave = (periodo["nave_id"], periodo["periodicidad_id"])
        if clave not in ultimos_periodos_cerrados:
            ultimos_periodos_cerrados[clave] = periodo

    periodos_vencidos = [
        periodo
        for periodo in ultimos_periodos_cerrados.values()
        if periodo["estado"] in estados_vencidos
    ]
    periodos_vencidos_total = len(periodos_vencidos)
    naves_con_vencidos = len({periodo["nave_id"] for periodo in periodos_vencidos})

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
        fichas_hoy=Count(
            "periodos__fichas",
            filter=Q(periodos__fichas__fecha_revision__date=timezone.localdate()),
            distinct=True,
        ),
    )

    if request.user.rol == "capitan":
        naves_activas = naves_activas.filter(id__in=naves_capitan)

    if query_busqueda:
        naves_activas = naves_activas.filter(
            Q(nombre__icontains=query_busqueda) | Q(matricula__icontains=query_busqueda)
        )

    page_obj = paginate(naves_activas.order_by("nombre"), request.GET.get("page"), 10)
    _params = request.GET.copy()
    _params.pop("page", None)
    pagination_params = _params.urlencode()

    actividad_reciente_qs = FichaRegistro.objects.filter(periodo__nave__naviera=request.naviera)
    if request.user.rol == "capitan":
        actividad_reciente_qs = actividad_reciente_qs.filter(periodo__nave__in=naves_capitan)
    actividad_reciente = list(
        actividad_reciente_qs
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
        "inspection/tierra/dashboard_tierra.html",
        {
            "page_obj": page_obj,
            "pagination_params": pagination_params,
            "query_busqueda": query_busqueda,
            "actividad_reciente": actividad_reciente,
            "total_usuarios": total_usuarios,
            "total_dispositivos": total_dispositivos,
            "fichas_hoy_total": fichas_hoy_total,
            "fallos_activos_total": fallos_activos_total,
            "fallos_nuevos_total": fallos_nuevos_total,
            "periodos_vencidos_total": periodos_vencidos_total,
            "naves_con_vencidos": naves_con_vencidos,
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
def fallos_activos(request, slug):
    naviera = request.naviera
    filtros_base = MatrizNaveRecurso.objects.filter(
        nave__naviera=naviera,
        nave__is_active=True,
        es_visible=True,
    )
    if request.user.rol == "capitan":
        filtros_base = filtros_base.filter(nave__in=FleetQueryService.get_naves_capitan(request.user, naviera))
    fallos_base = filtros_base.filter(ultimo_estado_operativo=False)
    qs = (
        fallos_base.select_related(
            "nave",
            "recurso__area",
            "recurso__periodicidad",
        )
        .order_by(F("ultimo_estado_operativo_en").desc(nulls_last=True), "nave__nombre", "recurso__nombre")
    )

    nave_id = request.GET.get("nave", "").strip()
    area_id = request.GET.get("area", "").strip()
    periodicidad_id = request.GET.get("periodicidad", "").strip()
    fecha_desde_str = request.GET.get("fecha_desde", "").strip()
    fecha_hasta_str = request.GET.get("fecha_hasta", "").strip()
    agrupar_por = request.GET.get("agrupar", "").strip()
    if agrupar_por not in {"", "nave", "area", "periodo"}:
        agrupar_por = ""

    solo_nuevos = request.GET.get("solo_nuevos") == "1"
    if solo_nuevos:
        qs = qs.filter(es_fallo_nuevo=True)

    if nave_id:
        try:
            qs = qs.filter(nave_id=int(nave_id))
        except ValueError:
            nave_id = ""

    if area_id:
        try:
            qs = qs.filter(recurso__area_id=int(area_id))
        except ValueError:
            area_id = ""

    if periodicidad_id:
        try:
            qs = qs.filter(recurso__periodicidad_id=int(periodicidad_id))
        except ValueError:
            periodicidad_id = ""

    if fecha_desde_str:
        try:
            fecha_desde = date.fromisoformat(fecha_desde_str)
            qs = qs.filter(ultimo_estado_operativo_en__date__gte=fecha_desde)
        except ValueError:
            fecha_desde_str = ""

    if fecha_hasta_str:
        try:
            fecha_hasta = date.fromisoformat(fecha_hasta_str)
            qs = qs.filter(ultimo_estado_operativo_en__date__lte=fecha_hasta)
        except ValueError:
            fecha_hasta_str = ""

    fallos_filtrados_total = qs.count()
    _params = request.GET.copy()
    _params.pop("page", None)
    if not agrupar_por:
        page_obj = paginate(qs, request.GET.get("page"), 20)
        fallos = list(page_obj.object_list)
        pagination_params = _params.urlencode()
    else:
        page_obj = None
        fallos = list(qs)
        pagination_params = ""
    presenters.adjuntar_detalle_a_fallos(fallos, naviera)
    grupos = []
    if agrupar_por == "nave":
        agrupado = {}
        for fallo in fallos:
            grupo = agrupado.setdefault(
                fallo.nave_id,
                {"label": fallo.nave.nombre, "sort_key": fallo.nave.nombre.lower(), "items": []},
            )
            grupo["items"].append(fallo)
        grupos = [grupo for grupo in sorted(agrupado.values(), key=lambda item: item["sort_key"])]
    elif agrupar_por == "area":
        agrupado = {}
        for fallo in fallos:
            if fallo.recurso.area_id:
                key = fallo.recurso.area_id
                label = fallo.recurso.area.nombre
                orden = fallo.recurso.area.orden if fallo.recurso.area.orden is not None else 9999
                sort_key = (0, orden, label.lower())
            else:
                key = None
                label = "Sin área"
                sort_key = (1, 9999, "")
            grupo = agrupado.setdefault(key, {"label": label, "sort_key": sort_key, "items": []})
            grupo["items"].append(fallo)
        grupos = [grupo for grupo in sorted(agrupado.values(), key=lambda item: item["sort_key"])]
    elif agrupar_por == "periodo":
        agrupado = {}
        for fallo in fallos:
            periodicidad = fallo.recurso.periodicidad
            if periodicidad:
                key = periodicidad.id
                label = periodicidad.nombre
                sort_key = (periodicidad.duracion_dias, periodicidad.nombre.lower())
            else:
                key = None
                label = "Sin periodicidad"
                sort_key = (99999, "")
            grupo = agrupado.setdefault(key, {"label": label, "sort_key": sort_key, "items": []})
            grupo["items"].append(fallo)
        grupos = [grupo for grupo in sorted(agrupado.values(), key=lambda item: item["sort_key"])]
    else:
        grupos = [{"label": None, "items": fallos}]

    naves = Nave.objects.filter(naviera=naviera, is_active=True).order_by("nombre")
    if request.user.rol == "capitan":
        naves = naves.filter(id__in=FleetQueryService.get_naves_capitan(request.user, naviera))
    areas = Area.objects.filter(
        id__in=filtros_base.exclude(recurso__area_id__isnull=True).values_list("recurso__area_id", flat=True)
    ).order_by(F("orden").asc(nulls_last=True), "nombre")
    periodicidades = Periodicidad.objects.filter(
        id__in=filtros_base.values_list("recurso__periodicidad_id", flat=True)
    ).order_by("duracion_dias", "nombre")

    total_fallos = fallos_base.count()
    naves_afectadas = fallos_base.values("nave").distinct().count()
    fallos_nuevos_total_sin_filtro = fallos_base.filter(es_fallo_nuevo=True).count()

    return render(
        request,
        "inspection/tierra/fallos_activos.html",
        {
            "slug": slug,
            "grupos": grupos,
            "agrupar_por": agrupar_por,
            "total_fallos": total_fallos,
            "naves_afectadas": naves_afectadas,
            "naves": naves,
            "areas": areas,
            "periodicidades": periodicidades,
            "nave_id": nave_id,
            "area_id": area_id,
            "periodicidad_id": periodicidad_id,
            "fecha_desde_str": fecha_desde_str,
            "fecha_hasta_str": fecha_hasta_str,
            "fallos_filtrados_total": fallos_filtrados_total,
            "page_obj": page_obj,
            "pagination_params": pagination_params,
            "solo_nuevos": solo_nuevos,
            "fallos_nuevos_total_sin_filtro": fallos_nuevos_total_sin_filtro,
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan", "tierra")
def periodos_vencidos(request, slug):
    naviera = request.naviera
    hoy = timezone.localdate()
    estados_vencidos = PeriodoRevision.ESTADOS_INCOMPLETOS

    qs = PeriodoRevision.objects.filter(
        nave__naviera=naviera,
        nave__is_active=True,
        estado__in=estados_vencidos,
    )
    if request.user.rol == "capitan":
        qs = qs.filter(nave__in=FleetQueryService.get_naves_capitan(request.user, naviera))
    qs = (
        qs
        .select_related("nave", "periodicidad")
        .order_by(F("fecha_termino").desc(nulls_last=True), "nave__nombre")
    )

    nave_id = request.GET.get("nave", "").strip()
    periodicidad_id = request.GET.get("periodicidad", "").strip()
    fecha_desde_str = request.GET.get("fecha_desde", "").strip()
    fecha_hasta_str = request.GET.get("fecha_hasta", "").strip()
    agrupar_por = request.GET.get("agrupar", "").strip()
    if agrupar_por not in {"", "nave", "periodo"}:
        agrupar_por = ""

    if nave_id:
        try:
            qs = qs.filter(nave_id=int(nave_id))
        except ValueError:
            nave_id = ""

    if periodicidad_id:
        try:
            qs = qs.filter(periodicidad_id=int(periodicidad_id))
        except ValueError:
            periodicidad_id = ""

    if fecha_desde_str:
        try:
            qs = qs.filter(fecha_termino__gte=date.fromisoformat(fecha_desde_str))
        except ValueError:
            fecha_desde_str = ""

    if fecha_hasta_str:
        try:
            qs = qs.filter(fecha_termino__lte=date.fromisoformat(fecha_hasta_str))
        except ValueError:
            fecha_hasta_str = ""

    fichas_completadas_sq = (
        FichaRegistro.objects.filter(
            periodo=OuterRef("pk"),
            estado_ficha="completa",
        )
        .values("periodo")
        .annotate(total=Count("id"))
        .values("total")
    )
    total_recursos_sq = (
        MatrizNaveRecurso.objects.filter(
            nave=OuterRef("nave"),
            recurso__periodicidad=OuterRef("periodicidad"),
            es_visible=True,
            recurso__created_at__date__lte=OuterRef("fecha_termino"),
        )
        .values("nave")
        .annotate(total=Count("id"))
        .values("total")
    )
    qs = qs.annotate(
        fichas_completadas=Subquery(fichas_completadas_sq, output_field=IntegerField()),
        total_recursos_momento=Subquery(total_recursos_sq, output_field=IntegerField()),
    )

    vencidos_filtrados_total = qs.count()
    _params = request.GET.copy()
    _params.pop("page", None)
    if not agrupar_por:
        page_obj = paginate(qs, request.GET.get("page"), 20)
        periodos = list(page_obj.object_list)
        pagination_params = _params.urlencode()
    else:
        page_obj = None
        periodos = list(qs)
        pagination_params = ""
    for periodo in periodos:
        periodo.tiempo_desde_vencimiento_display = presenters.formatear_tiempo_transcurrido_es(
            periodo.fecha_termino,
            ahora=hoy,
        )

    ultimos_cerrados_qs = PeriodoRevision.objects.filter(
        nave__naviera=naviera,
        nave__is_active=True,
        estado__in=TenantQueryService.ESTADOS_CERRADOS,
    )
    if request.user.rol == "capitan":
        ultimos_cerrados_qs = ultimos_cerrados_qs.filter(nave__in=FleetQueryService.get_naves_capitan(request.user, naviera))
    ultimos_cerrados = {}
    for periodo in (
        ultimos_cerrados_qs
        .select_related("nave", "periodicidad")
        .order_by("nave_id", "periodicidad_id", "-fecha_termino", "-id")
    ):
        clave = (periodo.nave_id, periodo.periodicidad_id)
        if clave not in ultimos_cerrados:
            ultimos_cerrados[clave] = periodo

    ultimos_vencidos = [
        periodo
        for periodo in ultimos_cerrados.values()
        if periodo.estado in estados_vencidos
    ]
    kpi_ultimos_vencidos = len(ultimos_vencidos)
    kpi_naves_afectadas = len({periodo.nave_id for periodo in ultimos_vencidos})

    kpi_total_historico = PeriodoRevision.objects.filter(
        nave__naviera=naviera,
        nave__is_active=True,
        estado__in=estados_vencidos,
    ).count()

    confiabilidad_por_periodicidad = TenantQueryService.calcular_confiabilidad_por_periodicidad(
        naviera, hoy
    )

    if agrupar_por == "nave":
        agrupado = {}
        for periodo in periodos:
            grupo = agrupado.setdefault(
                periodo.nave_id,
                {"label": periodo.nave.nombre, "sort_key": periodo.nave.nombre.lower(), "items": []},
            )
            grupo["items"].append(periodo)
        grupos = [grupo for grupo in sorted(agrupado.values(), key=lambda item: item["sort_key"])]
    elif agrupar_por == "periodo":
        agrupado = {}
        for periodo in periodos:
            grupo = agrupado.setdefault(
                periodo.periodicidad_id,
                {
                    "label": periodo.periodicidad.nombre,
                    "sort_key": (periodo.periodicidad.duracion_dias, periodo.periodicidad.nombre.lower()),
                    "items": [],
                },
            )
            grupo["items"].append(periodo)
        grupos = [grupo for grupo in sorted(agrupado.values(), key=lambda item: item["sort_key"])]
    else:
        grupos = [{"label": None, "items": periodos}]

    for grupo in grupos:
        grupo["items"].sort(key=lambda periodo: periodo.fecha_termino, reverse=True)

    naves = Nave.objects.filter(naviera=naviera, is_active=True).order_by("nombre")
    if request.user.rol == "capitan":
        naves = naves.filter(id__in=FleetQueryService.get_naves_capitan(request.user, naviera))
    periodicidades = Periodicidad.objects.filter(
        id__in=PeriodoRevision.objects.filter(
            nave__naviera=naviera,
            nave__is_active=True,
        ).values("periodicidad_id")
    ).order_by("duracion_dias", "nombre")

    return render(
        request,
        "inspection/tierra/periodos_vencidos.html",
        {
            "slug": slug,
            "grupos": grupos,
            "agrupar_por": agrupar_por,
            "kpi_ultimos_vencidos": kpi_ultimos_vencidos,
            "kpi_naves_afectadas": kpi_naves_afectadas,
            "kpi_total_historico": kpi_total_historico,
            "confiabilidad_por_periodicidad": confiabilidad_por_periodicidad,
            "vencidos_filtrados_total": vencidos_filtrados_total,
            "page_obj": page_obj,
            "pagination_params": pagination_params,
            "naves": naves,
            "periodicidades": periodicidades,
            "nave_id": nave_id,
            "periodicidad_id": periodicidad_id,
            "fecha_desde_str": fecha_desde_str,
            "fecha_hasta_str": fecha_hasta_str,
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan", "tierra")
def nave_detalle(request, slug, nave_id):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    if request.user.rol == "capitan" and not FleetQueryService.get_naves_capitan(request.user, request.naviera).filter(id=nave.id).exists():
        return HttpResponseForbidden("Acceso denegado.")
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
    periodos_abiertos_detalle = presenters.construir_periodos_detalle(nave, periodos_abiertos)
    historial_total = historial.count()
    _params = request.GET.copy()
    _params.pop("page", None)
    historial_page_obj = paginate(historial, request.GET.get("page"), 10)
    historial_detalle = presenters.construir_periodos_detalle(nave, historial_page_obj.object_list, for_history=True)
    historial_pagination_params = _params.urlencode()
    fallos_activos_nave = MatrizNaveRecurso.objects.filter(
        nave=nave,
        es_visible=True,
        ultimo_estado_operativo=False,
    ).count()
    fallos_nuevos_nave = MatrizNaveRecurso.objects.filter(
        nave=nave,
        es_visible=True,
        es_fallo_nuevo=True,
    ).count()
    periodos_vencidos_nave = PeriodoRevision.objects.filter(
        nave=nave,
        estado__in=PeriodoRevision.ESTADOS_INCOMPLETOS,
    ).count()
    total_recursos_nave = sum(item["total_recursos"] for item in periodos_abiertos_detalle)

    puede_ver_tripulacion = request.user.rol in {"admin_sitrep", "admin_naviera", "capitan", "tierra"}
    puede_editar_nave = request.user.rol in {"admin_sitrep", "admin_naviera"}

    return render(
        request,
        "inspection/tierra/nave_detalle.html",
        {
            "nave": nave,
            "periodos_abiertos_detalle": periodos_abiertos_detalle,
            "historial_detalle": historial_detalle,
            "historial_total": historial_total,
            "historial_page_obj": historial_page_obj,
            "historial_pagination_params": historial_pagination_params,
            "periodicidades": periodicidades,
            "fallos_activos_nave": fallos_activos_nave,
            "fallos_nuevos_nave": fallos_nuevos_nave,
            "periodos_vencidos_nave": periodos_vencidos_nave,
            "total_recursos_nave": total_recursos_nave,
            "slug": slug,
            "puede_ver_tripulacion": puede_ver_tripulacion,
            "puede_editar_nave": puede_editar_nave,
            "fecha_desde_str": filtros_historial["fecha_desde_str"],
            "fecha_hasta_str": filtros_historial["fecha_hasta_str"],
            "estado_filtro": filtros_historial["estado_filtro"],
            "periodicidad_id_filtro": filtros_historial["periodicidad_id_filtro"],
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan", "tierra")
def nave_periodo_pdf(request, slug, nave_id, periodo_id):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    if request.user.rol == "capitan" and not FleetQueryService.get_naves_capitan(request.user, request.naviera).filter(id=nave.id).exists():
        return HttpResponseForbidden("Acceso denegado.")

    try:
        periodo = PeriodoRevision.objects.select_related("periodicidad").get(
            id=periodo_id,
            nave=nave,
            estado__in=TenantQueryService.ESTADOS_ABIERTOS,
        )
    except PeriodoRevision.DoesNotExist:
        return redirect(f"/{slug}/naves/{nave.id}/detalle/")

    return generar_pdf_periodo(request, nave, periodo, slug)
