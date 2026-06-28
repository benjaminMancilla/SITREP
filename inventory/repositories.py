"""
Capa de acceso a DB.

Regla: cada función requiere naviera (o un objeto ya validado como nave/periodo
que pertenece implícitamente al tenant correcto). Nunca retorna datos de más de
un tenant. No aplica reglas de negocio — eso le corresponde a services.
"""
from django.db.models import F
from django.db.models.functions import Coalesce

from .models import FichaRegistro, PeriodoRevision


def get_periodo_de_nave(nave, periodo_id):
    """
    Retorna el PeriodoRevision que pertenece a esta nave, o None.
    La validación de tenant ya fue hecha al obtener `nave`.
    """
    try:
        return PeriodoRevision.objects.select_related("periodicidad").get(
            id=periodo_id,
            nave=nave,
        )
    except PeriodoRevision.DoesNotExist:
        return None


def get_datos_periodo_anterior(nave, periodo):
    """
    Busca el período cerrado más reciente para nave+periodicidad y retorna
    {recurso_id: {estado_operativo, observacion_general, payload_checklist}}.
    Solo incluye fichas con estado_operativo confirmado.
    Retorna {} si no hay período anterior.
    """
    ESTADOS_CERRADOS = {"operativo", "observado", "fallido", "omitido", "caduco"}
    periodo_anterior = (
        PeriodoRevision.objects.filter(
            nave=nave,
            periodicidad=periodo.periodicidad,
            estado__in=ESTADOS_CERRADOS,
            fecha_termino__lt=periodo.fecha_inicio,
        )
        .order_by("-fecha_termino")
        .first()
    )
    if not periodo_anterior:
        return {}

    return {
        ficha.recurso_id: {
            "estado_operativo": ficha.estado_operativo,
            "observacion_general": ficha.observacion_general or "",
            "payload_checklist": ficha.payload_checklist or {},
        }
        for ficha in FichaRegistro.objects.filter(
            periodo=periodo_anterior,
            estado_operativo__isnull=False,
        )
    }


def get_ultimas_fichas_fallidas(naviera, nave_ids, recurso_ids):
    """
    Retorna {(nave_id, recurso_id): FichaRegistro} con la ficha fallida más
    reciente por clave. Scoped a naviera para garantizar aislamiento tenant.
    """
    fichas_ordenadas = (
        FichaRegistro.objects.filter(
            periodo__nave__naviera=naviera,
            periodo__nave_id__in=nave_ids,
            recurso_id__in=recurso_ids,
            estado_operativo=False,
        )
        .select_related("usuario", "modificado_por", "periodo", "periodo__nave")
        .annotate(evento_en=Coalesce("modificado_en", "fecha_revision"))
        .order_by("periodo__nave_id", "recurso_id", F("evento_en").desc(), "-id")
    )

    ultimas = {}
    for ficha in fichas_ordenadas:
        clave = (ficha.periodo.nave_id, ficha.recurso_id)
        if clave not in ultimas:
            ultimas[clave] = ficha
    return ultimas


def get_fichas_de_recursos_en_periodo(periodo, recurso_ids):
    """
    Retorna {recurso_id: FichaRegistro} para los recursos dados en el período.
    El período ya está validado al tenant correcto.
    """
    return {
        ficha.recurso_id: ficha
        for ficha in FichaRegistro.objects.filter(
            periodo=periodo,
            recurso_id__in=recurso_ids,
        ).select_related("usuario", "modificado_por")
    }


def get_fichas_de_periodos_raw(periodo_ids):
    """
    Retorna queryset de FichaRegistro para los períodos dados.
    Solo carga campos necesarios para evaluar completitud.
    Destinado a ser procesado con MotorPeriodos._es_ficha_completa en la capa de servicio.
    """
    if not periodo_ids:
        return FichaRegistro.objects.none()
    return (
        FichaRegistro.objects.filter(periodo_id__in=periodo_ids)
        .select_related("recurso")
        .only("periodo_id", "estado_operativo", "payload_checklist", "recurso__requerimientos")
    )


def get_brutos_urgencia(naviera):
    """
    Retorna los datos crudos necesarios para construir la tabla de urgencia.
    Todos los queries están scoped a naviera — garantía de aislamiento tenant.
    Retorna None si no hay naves activas.

    Estructura retornada:
    {
        "naves": list[Nave],
        "periodos_por_clave": dict[(nave_id, periodicidad_id), PeriodoRevision],
        "fichas_raw": QuerySet[FichaRegistro],   # sin evaluar completitud
        "totales": dict[(nave_id, periodicidad_id), int],
        "fallos": dict[(nave_id, periodicidad_id), int],
        "fallos_nuevos": dict[(nave_id, periodicidad_id), int],
    }
    """
    from django.db.models import Count

    from .models import MatrizNaveRecurso, Nave, PeriodoRevision
    from .services import TenantQueryService

    estados_cerrados = {"operativo", "observado", "fallido", "omitido", "caduco"}
    estados_relevantes = TenantQueryService.ESTADOS_ABIERTOS | estados_cerrados

    naves = list(Nave.objects.for_naviera(naviera).filter(is_active=True).order_by("nombre"))
    if not naves:
        return None

    nave_ids = [nave.id for nave in naves]

    periodos_ordenados = list(
        PeriodoRevision.objects.filter(
            nave_id__in=nave_ids,
            estado__in=estados_relevantes,
        )
        .select_related("periodicidad")
        .order_by("nave_id", "periodicidad_id", "-fecha_inicio", "-id")
    )

    periodos_por_clave = {}
    for periodo in periodos_ordenados:
        clave = (periodo.nave_id, periodo.periodicidad_id)
        if clave not in periodos_por_clave:
            periodos_por_clave[clave] = periodo

    periodo_ids = [p.id for p in periodos_por_clave.values()] or [-1]

    totales = {
        (item["nave_id"], item["recurso__periodicidad_id"]): item["total"]
        for item in MatrizNaveRecurso.objects.filter(
            nave_id__in=nave_ids,
            es_visible=True,
        )
        .values("nave_id", "recurso__periodicidad_id")
        .annotate(total=Count("id"))
    }

    fallos = {
        (item["nave_id"], item["recurso__periodicidad_id"]): item["total"]
        for item in MatrizNaveRecurso.objects.filter(
            nave_id__in=nave_ids,
            es_visible=True,
            ultimo_estado_operativo=False,
        )
        .values("nave_id", "recurso__periodicidad_id")
        .annotate(total=Count("id"))
    }

    fallos_nuevos = {
        (item["nave_id"], item["recurso__periodicidad_id"]): item["total"]
        for item in MatrizNaveRecurso.objects.filter(
            nave_id__in=nave_ids,
            es_visible=True,
            es_fallo_nuevo=True,
        )
        .values("nave_id", "recurso__periodicidad_id")
        .annotate(total=Count("id"))
    }

    return {
        "naves": naves,
        "periodos_por_clave": periodos_por_clave,
        "fichas_raw": get_fichas_de_periodos_raw(periodo_ids),
        "totales": totales,
        "fallos": fallos,
        "fallos_nuevos": fallos_nuevos,
    }
