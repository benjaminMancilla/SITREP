import bisect
import json
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib.auth import authenticate, login, logout
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, F, IntegerField, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, Greatest
from django.http import Http404, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.utils.text import slugify
from django.utils import timezone

from .decorators import requiere_rol, tenant_member_required
from .models import (
    Area,
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
CONFIABILIDAD_UMBRALES = [1, 7, 30, 90, 365]
CONFIABILIDAD_VENTANAS = [30, 30, 90, 365, 730, 1825]


def _ventana_confiabilidad(duracion_dias):
    """
    Retorna la ventana de confiabilidad en días para una periodicidad.
    Usa bisect_left para encontrar el intervalo correcto en O(log n).
    """
    indice = bisect.bisect_left(CONFIABILIDAD_UMBRALES, duracion_dias)
    return CONFIABILIDAD_VENTANAS[indice]


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


def _calcular_urgencia(dias_restantes, duracion_total, cobertura):
    if duracion_total == 0:
        return 0.0
    dias_restantes = min(max(0, dias_restantes), duracion_total)
    tiempo_norm = (duracion_total - dias_restantes) / duracion_total
    return round((1.0 - cobertura) * tiempo_norm, 4)


def _numero_periodo(periodo, nave):
    """
    Calcula el número ordinal del período dentro del año de la nave.
    El año se cuenta desde nave.agregado_en (no año calendario).
    """
    fecha_entrada_raw = getattr(nave, "agregado_en", None)
    if not fecha_entrada_raw:
        return None

    fecha_entrada = (
        fecha_entrada_raw.date()
        if hasattr(fecha_entrada_raw, "date")
        else fecha_entrada_raw
    )
    duracion = periodo.periodicidad.duracion_dias or 1
    dias_desde_entrada = (periodo.fecha_inicio - fecha_entrada).days
    if dias_desde_entrada < 0:
        return None

    periodos_por_anno = max(1, 365 // duracion)
    return (dias_desde_entrada // duracion) % periodos_por_anno + 1


def _etiqueta_numero_periodicidad(periodicidad):
    nombre = (periodicidad.nombre or "").strip()
    etiquetas = {
        "quincenal": "Quincena",
        "semanal": "Semana",
        "mensual": "Mes",
        "trimestral": "Trimestre",
        "anual": "Año",
    }
    return etiquetas.get(nombre.casefold(), nombre)


def _construir_datos_tabla_urgencia(naviera):
    estados_cerrados = {"operativo", "observado", "fallido", "omitido", "caduco"}
    estados_relevantes = TenantQueryService.ESTADOS_ABIERTOS | estados_cerrados
    hoy = date.today()

    naves = list(Nave.objects.filter(naviera=naviera, is_active=True).order_by("nombre"))
    if not naves:
        return {"columns": [], "naves": []}

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

    periodos = list(periodos_por_clave.values())
    periodo_ids = [periodo.id for periodo in periodos] or [-1]

    fichas_completas = {periodo_id: 0 for periodo_id in periodo_ids}
    for ficha in (
        FichaRegistro.objects.filter(periodo_id__in=periodo_ids)
        .select_related("recurso")
        .only("periodo_id", "estado_operativo", "payload_checklist", "recurso__requerimientos")
    ):
        if MotorPeriodos._es_ficha_completa(ficha):
            fichas_completas[ficha.periodo_id] += 1

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

    periodicidades_activas = {}
    for periodo in periodos:
        if periodo.estado in TenantQueryService.ESTADOS_ABIERTOS:
            periodicidades_activas[periodo.periodicidad_id] = periodo.periodicidad

    periodicidades_ordenadas = sorted(
        periodicidades_activas.values(),
        key=lambda periodicidad: (
            periodicidad.duracion_dias,
            periodicidad.nombre.lower(),
            periodicidad.id,
        ),
    )

    keys_por_periodicidad = {}
    used_keys = set()
    columns = []
    for periodicidad in periodicidades_ordenadas:
        key_source = getattr(periodicidad, "nombre_tecnico", None) or periodicidad.nombre
        base_key = slugify(key_source).replace("-", "_") or f"periodicidad_{periodicidad.id}"
        key = base_key
        if key in used_keys:
            key = f"{base_key}_{periodicidad.id}"
        used_keys.add(key)
        keys_por_periodicidad[periodicidad.id] = key
        columns.append(
            {
                "key": key,
                "label": periodicidad.nombre,
            }
        )

    periodicidad_ids_activas = {periodicidad.id for periodicidad in periodicidades_ordenadas}
    naves_data = []
    for nave in naves:
        periodos_nave = {column["key"]: None for column in columns}

        for periodicidad_id in periodicidad_ids_activas:
            periodo = periodos_por_clave.get((nave.id, periodicidad_id))
            if periodo is None:
                continue

            total_recursos = totales.get((nave.id, periodicidad_id), 0)
            cobertura = (
                1.0
                if total_recursos == 0
                else min(1.0, round(fichas_completas.get(periodo.id, 0) / total_recursos, 4))
            )
            es_periodo_abierto = periodo.estado in TenantQueryService.ESTADOS_ABIERTOS
            dias_restantes = max(0, (periodo.fecha_termino - hoy).days) if es_periodo_abierto else 0
            duracion_total = periodo.periodicidad.duracion_dias or 0
            key = keys_por_periodicidad[periodicidad_id]

            periodos_nave[key] = {
                "estado": "en_curso" if es_periodo_abierto else periodo.estado,
                "urgencia": (
                    _calcular_urgencia(dias_restantes, duracion_total, cobertura)
                    if es_periodo_abierto
                    else None
                ),
                "cobertura": cobertura,
                "dias_restantes": dias_restantes,
                "duracion_total": duracion_total,
                "fallos": fallos.get((nave.id, periodicidad_id), 0),
                "fecha_cierre": (
                    None if es_periodo_abierto else periodo.fecha_termino.strftime("%d/%m/%Y")
                ),
            }

        naves_data.append(
            {
                "id": nave.id,
                "nombre": nave.nombre,
                "matricula": nave.matricula,
                "periodos": periodos_nave,
            }
        )

    return {"columns": columns, "naves": naves_data}


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


def _nombre_usuario_display(usuario):
    if not usuario:
        return ""
    nombre_completo = f"{usuario.first_name} {usuario.last_name}".strip()
    return nombre_completo or usuario.rut


def _formatear_tiempo_transcurrido_es(fecha, ahora=None):
    if not fecha:
        return ""

    if isinstance(fecha, datetime):
        if ahora is None:
            ahora = timezone.now()
        if timezone.is_naive(fecha):
            fecha = timezone.make_aware(fecha, timezone.get_current_timezone())
        delta = ahora - fecha
        total_segundos = max(0, int(delta.total_seconds()))
    else:
        if isinstance(ahora, datetime):
            hoy = timezone.localdate(ahora)
        elif isinstance(ahora, date):
            hoy = ahora
        else:
            hoy = timezone.localdate()
        total_segundos = max(0, (hoy - fecha).days) * 24 * 60 * 60

    unidades = (
        ("día", "días", 24 * 60 * 60),
        ("hora", "horas", 60 * 60),
        ("minuto", "minutos", 60),
    )
    partes = []
    resto = total_segundos

    for singular, plural, segundos_unidad in unidades:
        valor, resto = divmod(resto, segundos_unidad)
        if valor:
            etiqueta = singular if valor == 1 else plural
            partes.append(f"{valor} {etiqueta}")
        if len(partes) == 2:
            break

    return ", ".join(partes) if partes else "menos de 1 minuto"


def _adjuntar_detalle_a_fallos(fallos, naviera):
    if not fallos:
        return

    ahora = timezone.now()
    nave_ids = {fallo.nave_id for fallo in fallos}
    recurso_ids = {fallo.recurso_id for fallo in fallos}
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

    ultimas_fichas = {}
    for ficha in fichas_ordenadas:
        clave = (ficha.periodo.nave_id, ficha.recurso_id)
        if clave not in ultimas_fichas:
            ultimas_fichas[clave] = ficha

    for fallo in fallos:
        fallo.tiempo_desde_display = _formatear_tiempo_transcurrido_es(
            fallo.ultimo_estado_operativo_en,
            ahora=ahora,
        )
        ficha = ultimas_fichas.get((fallo.nave_id, fallo.recurso_id))
        fallo.ficha_detalle = ficha
        fallo.ficha_usuario_display = _nombre_usuario_display(
            (ficha.modificado_por or ficha.usuario) if ficha else None
        )
        fallo.ficha_evento_en = (
            ficha.modificado_en or ficha.fecha_revision
            if ficha else None
        )
        fallo.ficha_observacion_general = (
            (ficha.observacion_general or "").strip()
            if ficha else ""
        )

        if not ficha:
            fallo.checklist_fallido = []
            continue

        payload_actual = MotorFichas.normalizar_payload_checklist(ficha.payload_checklist or {})
        checklist_items = MotorFichas.construir_checklist_items(
            recurso=fallo.recurso,
            cantidad=fallo.cantidad,
            payload_checklist=payload_actual,
            incluir_requisito_cantidad=MotorFichas.CANTIDAD_REQUISITO_KEY in payload_actual,
        )
        fallo.checklist_fallido = [
            item for item in checklist_items
            if item["checked"] is False
        ]


def _construir_periodos_detalle(nave, periodos):
    periodos_detalle = []
    # TODO: optimizar con annotate() y prefetch_related en Fase 4
    for periodo in periodos:
        numero_periodo = _numero_periodo(periodo, nave)
        fichas = list(
            TenantQueryService.get_fichas_de_periodo(periodo).order_by(
                F("recurso__area__orden").asc(nulls_last=True),
                F("recurso__area__nombre").asc(nulls_last=True),
                "recurso__nombre",
            )
        )
        matrices = list(
            TenantQueryService.get_recursos_visibles_de_nave_en_periodo(nave, periodo).order_by(
                F("recurso__area__orden").asc(nulls_last=True),
                F("recurso__area__nombre").asc(nulls_last=True),
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

            payload_actual = MotorFichas.normalizar_payload_checklist(ficha.payload_checklist or {})
            checklist_items = MotorFichas.construir_checklist_items(
                recurso=matriz.recurso,
                cantidad=matriz.cantidad,
                payload_checklist=payload_actual,
                incluir_requisito_cantidad=MotorFichas.CANTIDAD_REQUISITO_KEY in payload_actual,
            )

            registros.append(
                {
                    "tipo": "ficha",
                    "recurso": matriz.recurso,
                    "matriz": matriz,
                    "ficha": ficha,
                    "estado_operativo": ficha.estado_operativo,
                    "checklist_items": checklist_items,
                }
            )

        periodos_detalle.append(
            {
                "periodo": periodo,
                "numero": numero_periodo,
                "numero_label": _etiqueta_numero_periodicidad(periodo.periodicidad),
                "fichas": fichas,
                "registros": registros,
                "registros_por_area": _agrupar_registros_por_area(registros),
                "total_recursos": total_recursos,
                "fichas_count": fichas_count,
                "fallos_count": fallos_count,
                "has_fallos": fallos_count > 0,
                "avance_pct": int((fichas_count * 100) / total_recursos) if total_recursos else 0,
            }
        )
    return periodos_detalle


def _parse_estado_checklist_form(raw_estado):
    if raw_estado == "on":
        return True
    if raw_estado == "off":
        return False
    return None


def _construir_recursos_lista_periodo(nave, periodo, slug=None, for_history=False):
    matrices = TenantQueryService.get_recursos_visibles_de_nave_en_periodo(nave, periodo)
    if for_history:
        matrices = matrices.filter(recurso__created_at__date__lte=periodo.fecha_termino)

    matrices = list(matrices)
    matrices.sort(key=_clave_orden_matriz_recurso_periodo)

    fichas_por_recurso_id = {
        ficha.recurso_id: ficha
        for ficha in FichaRegistro.objects.filter(
            periodo=periodo,
            recurso_id__in=[matriz.recurso_id for matriz in matrices],
        ).select_related("usuario", "modificado_por")
    }

    recursos_lista = []
    for matriz in matrices:
        ficha = fichas_por_recurso_id.get(matriz.recurso_id)
        payload_actual = MotorFichas.normalizar_payload_checklist(
            ficha.payload_checklist if ficha else {}
        )
        incluir_requisito_cantidad = matriz.cantidad > 1 and (
            not for_history or MotorFichas.CANTIDAD_REQUISITO_KEY in payload_actual
        )
        checklist_items = MotorFichas.construir_checklist_items(
            recurso=matriz.recurso,
            cantidad=matriz.cantidad,
            payload_checklist=payload_actual,
            incluir_requisito_cantidad=incluir_requisito_cantidad,
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


def _extraer_indice_codigo_recurso(codigo):
    codigo = (codigo or "").strip()
    if not codigo:
        return None

    match = re.match(r"^\d+\.(\d+)", codigo)
    if not match:
        return None

    return int(match.group(1))


def _clave_orden_area(area):
    if area is None:
        return (True, True, float("inf"), "sin área", float("inf"))

    nombre_display = _nombre_display_area(area).casefold()
    return (
        False,
        area.orden is None,
        area.orden if area.orden is not None else float("inf"),
        nombre_display,
        area.id,
    )


def _clave_orden_matriz_recurso_periodo(matriz):
    recurso = matriz.recurso
    return _clave_orden_recurso(recurso)


def _clave_orden_recurso(recurso):
    area = recurso.area
    codigo = (recurso.codigo or "").strip()
    indice_codigo = _extraer_indice_codigo_recurso(codigo)

    return (
        *_clave_orden_area(area),
        indice_codigo is None,
        indice_codigo if indice_codigo is not None else float("inf"),
        codigo.casefold(),
        (recurso.nombre or "").casefold(),
        recurso.id,
    )


def _agrupar_recursos_por_area(recursos_lista):
    """
    Agrupa recursos_lista por área. Los recursos sin área van al final
    en un grupo especial con area=None.
    Retorna lista de dicts:
    [
        {
            "area": <Area instance o None>,
            "nombre_display": "Salvamento" o "Sin área",
            "recursos": [...items de recursos_lista...],
            "total": int,
            "con_ficha": int,
            "tiene_fallo": bool,
        },
        ...
    ]
    """
    grupos_por_area = {}

    for item in recursos_lista:
        area = item["recurso"].area
        area_id = area.id if area is not None else None

        if area_id not in grupos_por_area:
            grupos_por_area[area_id] = {
                "area": area,
                "nombre_display": _nombre_display_area(area),
                "recursos": [],
                "total": 0,
                "con_ficha": 0,
                "tiene_fallo": False,
            }

        grupo = grupos_por_area[area_id]
        grupo["recursos"].append(item)
        grupo["total"] += 1
        if item["tiene_ficha"]:
            grupo["con_ficha"] += 1
        if item["estado_operativo"] is False:
            grupo["tiene_fallo"] = True

    for grupo in grupos_por_area.values():
        grupo["recursos"].sort(key=lambda item: _clave_orden_recurso(item["recurso"]))

    return _ordenar_grupos_por_area(grupos_por_area)


def _agrupar_registros_por_area(registros):
    grupos_por_area = {}

    for registro in registros:
        area = registro["recurso"].area
        area_id = area.id if area is not None else None

        if area_id not in grupos_por_area:
            grupos_por_area[area_id] = {
                "area": area,
                "nombre_display": _nombre_display_area(area),
                "registros": [],
                "total": 0,
                "con_ficha": 0,
            }

        grupo = grupos_por_area[area_id]
        grupo["registros"].append(registro)
        grupo["total"] += 1
        if registro["tipo"] == "ficha":
            grupo["con_ficha"] += 1

    for grupo in grupos_por_area.values():
        grupo["registros"].sort(key=lambda registro: _clave_orden_recurso(registro["recurso"]))

    return _ordenar_grupos_por_area(grupos_por_area)


def _nombre_display_area(area):
    if area is None:
        return "Sin área"
    return (area.nombre_tecnico or area.nombre or "").strip() or area.nombre


def _ordenar_grupos_por_area(grupos_por_area):
    grupos_con_area = [grupo for grupo in grupos_por_area.values() if grupo["area"] is not None]
    grupos_con_area.sort(key=lambda grupo: _clave_orden_area(grupo["area"]))

    grupo_sin_area = grupos_por_area.get(None)
    if grupo_sin_area is not None:
        grupos_con_area.append(grupo_sin_area)

    return grupos_con_area


def _cargar_payload_json(request):
    try:
        return json.loads(request.body), None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, _json_error("JSON inválido.", 400)


def _validar_payload_ficha_dict(payload, require_recurso_id=False):
    if not isinstance(payload, dict):
        return None, "La ficha debe ser un objeto JSON."

    data = {}
    if require_recurso_id:
        recurso_id = payload.get("recurso_id")
        if type(recurso_id) is not int:
            return None, "recurso_id debe ser entero."
        data["recurso_id"] = recurso_id

    estado_operativo = payload.get("estado_operativo")
    observacion_general = payload.get("observacion_general", "")
    payload_checklist = payload.get("payload_checklist", {})

    if estado_operativo is not None and type(estado_operativo) is not bool:
        return None, "estado_operativo debe ser booleano o null."
    if not isinstance(observacion_general, str):
        return None, "observacion_general debe ser texto."
    if not isinstance(payload_checklist, dict):
        return None, "payload_checklist debe ser un objeto JSON."

    data.update(
        {
            "estado_operativo": estado_operativo,
            "observacion_general": observacion_general,
            "payload_checklist": payload_checklist,
        }
    )
    return data, None


def _extraer_payload_ficha_desde_json(request):
    payload, error = _cargar_payload_json(request)
    if error:
        return None, error

    data, mensaje_error = _validar_payload_ficha_dict(payload)
    if mensaje_error:
        if not isinstance(payload, dict):
            return None, _json_error("El body debe ser un objeto JSON.", 400)
        return None, _json_error(mensaje_error, 400)

    return data, None


def _extraer_payload_fichas_bulk_desde_json(request):
    payload, error = _cargar_payload_json(request)
    if error:
        return None, error

    if not isinstance(payload, dict):
        return None, _json_error("El body debe ser un objeto JSON.", 400)

    fichas = payload.get("fichas")
    if not isinstance(fichas, list):
        return None, _json_error("fichas debe ser una lista.", 400)

    return fichas, None


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan", "tierra")
def dashboard_tierra(request, slug):
    total_usuarios = TenantQueryService.get_usuarios_del_tenant(request.naviera).count()
    total_dispositivos = Dispositivo.objects.filter(naviera=request.naviera, is_active=True).count()
    fichas_hoy_total = FichaRegistro.objects.filter(
        periodo__nave__naviera=request.naviera,
        fecha_revision__date=timezone.localdate(),
    ).count()
    fallos_activos_total = MatrizNaveRecurso.objects.filter(
        nave__naviera=request.naviera,
        nave__is_active=True,
        es_visible=True,
        ultimo_estado_operativo=False,
    ).count()
    estados_cerrados = {"operativo", "observado", "fallido", "omitido", "caduco"}
    estados_vencidos = {"omitido", "caduco"}
    todos_periodos_cerrados = (
        PeriodoRevision.objects.filter(
            nave__naviera=request.naviera,
            nave__is_active=True,
            estado__in=estados_cerrados,
        )
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
            "matriz_recursos",
            filter=Q(
                matriz_recursos__es_visible=True,
                matriz_recursos__ultimo_estado_operativo=False,
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

    actividad_reciente = list(
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
    tabla_urgencia = _construir_datos_tabla_urgencia(request.naviera)

    return render(
        request,
        "inventory/dashboard_tierra.html",
        {
            "page_obj": page_obj,
            "query_busqueda": query_busqueda,
            "actividad_reciente": actividad_reciente,
            "tabla_urgencia_json": tabla_urgencia,
            "total_usuarios": total_usuarios,
            "total_dispositivos": total_dispositivos,
            "fichas_hoy_total": fichas_hoy_total,
            "fallos_activos_total": fallos_activos_total,
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

    fallos = list(qs)
    _adjuntar_detalle_a_fallos(fallos, naviera)
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
    areas = Area.objects.filter(
        id__in=filtros_base.exclude(recurso__area_id__isnull=True).values_list("recurso__area_id", flat=True)
    ).order_by(F("orden").asc(nulls_last=True), "nombre")
    periodicidades = Periodicidad.objects.filter(
        id__in=filtros_base.values_list("recurso__periodicidad_id", flat=True)
    ).order_by("duracion_dias", "nombre")

    total_fallos = fallos_base.count()
    naves_afectadas = fallos_base.values("nave").distinct().count()

    return render(
        request,
        "inventory/fallos_activos.html",
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
            "fallos_filtrados_total": len(fallos),
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan", "tierra")
def periodos_vencidos(request, slug):
    naviera = request.naviera
    hoy = timezone.localdate()
    estados_vencidos = {"omitido", "caduco"}
    estados_cerrados = estados_vencidos | {"operativo", "observado", "fallido"}

    qs = (
        PeriodoRevision.objects.filter(
            nave__naviera=naviera,
            nave__is_active=True,
            estado__in=estados_vencidos,
        )
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

    periodos = list(qs)
    for periodo in periodos:
        periodo.tiempo_desde_vencimiento_display = _formatear_tiempo_transcurrido_es(
            periodo.fecha_termino,
            ahora=hoy,
        )

    ultimos_cerrados = {}
    for periodo in (
        PeriodoRevision.objects.filter(
            nave__naviera=naviera,
            nave__is_active=True,
            estado__in=estados_cerrados,
        )
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

    periodicidad_ids_con_historial = (
        PeriodoRevision.objects.filter(
            nave__naviera=naviera,
            nave__is_active=True,
        )
        .values_list("periodicidad_id", flat=True)
        .distinct()
    )
    confiabilidad_por_periodicidad = []
    for periodicidad in Periodicidad.objects.filter(id__in=periodicidad_ids_con_historial).order_by(
        "duracion_dias", "nombre"
    ):
        ventana = _ventana_confiabilidad(periodicidad.duracion_dias)
        desde = hoy - timedelta(days=ventana)
        total_cerrados = PeriodoRevision.objects.filter(
            nave__naviera=naviera,
            nave__is_active=True,
            periodicidad=periodicidad,
            estado__in=estados_cerrados,
            fecha_termino__gte=desde,
        ).count()
        vencidos_ventana = PeriodoRevision.objects.filter(
            nave__naviera=naviera,
            nave__is_active=True,
            periodicidad=periodicidad,
            estado__in=estados_vencidos,
            fecha_termino__gte=desde,
        ).count()
        if total_cerrados > 0:
            confiabilidad_por_periodicidad.append(
                {
                    "periodicidad": periodicidad,
                    "ventana_dias": ventana,
                    "total": total_cerrados,
                    "vencidos": vencidos_ventana,
                    "pct_cumplimiento": round(
                        100 * (total_cerrados - vencidos_ventana) / total_cerrados
                    ),
                }
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
    periodicidades = Periodicidad.objects.filter(
        id__in=PeriodoRevision.objects.filter(
            nave__naviera=naviera,
            nave__is_active=True,
        ).values("periodicidad_id")
    ).order_by("duracion_dias", "nombre")

    return render(
        request,
        "inventory/periodos_vencidos.html",
        {
            "slug": slug,
            "grupos": grupos,
            "agrupar_por": agrupar_por,
            "kpi_ultimos_vencidos": kpi_ultimos_vencidos,
            "kpi_naves_afectadas": kpi_naves_afectadas,
            "kpi_total_historico": kpi_total_historico,
            "confiabilidad_por_periodicidad": confiabilidad_por_periodicidad,
            "vencidos_filtrados_total": len(periodos),
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
    fallos_activos_nave = MatrizNaveRecurso.objects.filter(
        nave=nave,
        es_visible=True,
        ultimo_estado_operativo=False,
    ).count()
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
    hoy = timezone.localdate()
    # TODO: optimizar con annotate() en Fase 4
    for periodo in periodos_abiertos:
        numero_periodo = _numero_periodo(periodo, nave)
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
                "numero_label": _etiqueta_numero_periodicidad(periodo.periodicidad),
                "total_recursos": total_recursos,
                "fichas_completadas": fichas_completadas,
                "completado": fichas_completadas >= total_recursos,
                "dias_restantes": max(0, (periodo.fecha_termino - hoy).days),
            }
        )
    for periodo in historial:
        periodo.fichas_completadas_count = fichas_completadas_count.get(periodo.id, 0)
        periodo.numero_periodo = _numero_periodo(periodo, nave)
        periodo.numero_periodo_label = _etiqueta_numero_periodicidad(periodo.periodicidad)

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
    datos_anterior = _obtener_datos_periodo_anterior(nave, periodo)
    for item in recursos_lista:
        ficha_anterior = datos_anterior.get(item["recurso"].id)
        for checklist_item in item["checklist_items"]:
            if ficha_anterior:
                payload_item = ficha_anterior["payload_checklist"].get(checklist_item["key"], {})
                if isinstance(payload_item, dict) and "cumple" in payload_item:
                    checklist_item["periodo_anterior"] = {
                        "estado": payload_item.get("cumple"),
                        "obs": payload_item.get("observacion", ""),
                    }
                else:
                    checklist_item["periodo_anterior"] = {"estado": None, "obs": ""}
            else:
                checklist_item["periodo_anterior"] = {"estado": None, "obs": ""}

        item["periodo_anterior_json"] = json.dumps(
            {
                "obsGeneral": (
                    ficha_anterior["observacion_general"] if ficha_anterior else ""
                ),
                "checklist": {
                    checklist_item["key"]: checklist_item["periodo_anterior"]
                    for checklist_item in item["checklist_items"]
                },
            },
            ensure_ascii=False,
        ).replace("</", "<\\/")

    areas_grupos = _agrupar_recursos_por_area(recursos_lista)
    fichas_completadas_count = sum(1 for item in recursos_lista if item["tiene_ficha"])
    numero_periodo = _numero_periodo(periodo, nave)

    return render(
        request,
        "inventory/kiosco_periodo_detalle.html",
        {
            "nave": nave,
            "periodo": periodo,
            "numero_periodo": numero_periodo,
            "numero_periodo_label": _etiqueta_numero_periodicidad(periodo.periodicidad),
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

    ESTADOS_CERRADOS = {"operativo", "observado", "fallido", "omitido", "caduco"}
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

    recursos_lista = _construir_recursos_lista_periodo(nave, periodo, for_history=True)
    areas_grupos = _agrupar_recursos_por_area(recursos_lista)

    return render(
        request,
        "inventory/kiosco_periodo_historial.html",
        {
            "nave": nave,
            "periodo": periodo,
            "numero_periodo": _numero_periodo(periodo, nave),
            "numero_periodo_label": _etiqueta_numero_periodicidad(periodo.periodicidad),
            "areas_grupos": areas_grupos,
            "recursos_lista": recursos_lista,
            "slug": slug,
        },
    )


def _obtener_datos_periodo_anterior(nave, periodo):
    """
    Busca el período cerrado más reciente para nave+periodicidad
    y retorna un dict {recurso_id: {estado_operativo, observacion_general, payload_checklist}}.
    Solo incluye fichas con estado_operativo confirmado (not None).
    Si no hay período anterior, retorna {}.
    """
    estados_cerrados = getattr(
        TenantQueryService,
        "ESTADOS_CERRADOS",
        {"operativo", "observado", "fallido", "omitido", "caduco"},
    )
    periodo_anterior = (
        PeriodoRevision.objects.filter(
            nave=nave,
            periodicidad=periodo.periodicidad,
            estado__in=estados_cerrados,
            fecha_termino__lt=periodo.fecha_inicio,
        )
        .order_by("-fecha_termino")
        .first()
    )
    if not periodo_anterior:
        return {}

    fichas = FichaRegistro.objects.filter(
        periodo=periodo_anterior,
        estado_operativo__isnull=False,
    )
    return {
        ficha.recurso_id: {
            "estado_operativo": ficha.estado_operativo,
            "observacion_general": ficha.observacion_general or "",
            "payload_checklist": ficha.payload_checklist or {},
        }
        for ficha in fichas
    }


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
            incluir_requisito_cantidad=matriz.cantidad > 1,
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
        incluir_requisito_cantidad=matriz.cantidad > 1,
    )
    datos_anterior = _obtener_datos_periodo_anterior(nave, periodo)
    ficha_anterior = datos_anterior.get(recurso.id)

    for item in checklist_items:
        if ficha_anterior:
            payload_item = ficha_anterior["payload_checklist"].get(item["key"], {})
            if isinstance(payload_item, dict) and "cumple" in payload_item:
                item["periodo_anterior"] = {
                    "estado": payload_item.get("cumple"),
                    "obs": payload_item.get("observacion", ""),
                }
            else:
                item["periodo_anterior"] = {"estado": None, "obs": ""}
        else:
            item["periodo_anterior"] = {"estado": None, "obs": ""}

    obs_general_anterior = ficha_anterior["observacion_general"] if ficha_anterior else ""
    periodo_anterior_json = json.dumps(
        {
            "obsGeneral": obs_general_anterior,
            "checklist": {
                item["key"]: item["periodo_anterior"]
                for item in checklist_items
            },
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")

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
            "periodo_anterior_json": periodo_anterior_json,
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
            "matriz_recursos",
            filter=Q(
                matriz_recursos__es_visible=True,
                matriz_recursos__ultimo_estado_operativo=False,
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
                "checklist_items": MotorFichas.construir_checklist_items(
                    recurso=matriz.recurso,
                    cantidad=matriz.cantidad,
                    payload_checklist=ficha.payload_checklist if ficha else {},
                    incluir_requisito_cantidad=matriz.cantidad > 1,
                ),
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
            "checklist_items": MotorFichas.construir_checklist_items(
                recurso=matriz.recurso,
                cantidad=matriz.cantidad,
                payload_checklist=payload_checklist,
                incluir_requisito_cantidad=matriz.cantidad > 1,
            ),
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


@tenant_member_required
@requiere_rol("mar", "capitan", "tierra", "admin_naviera", "admin_sitrep")
def api_guardar_fichas_periodo(request, slug, periodo_id):
    """
    POST: recibe lista de fichas con cambios y las crea/actualiza en una transacción.
    Solo procesa los recursos incluidos en el payload — no sobreescribe lo no enviado.
    """
    if request.method != "POST":
        return _json_error("Método no permitido.", 405)

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = _obtener_periodo_de_nave(nave, periodo_id)
    if periodo is None or periodo.estado not in TenantQueryService.ESTADOS_ABIERTOS:
        return _json_error("Período no encontrado.", 404)

    fichas_payload, error = _extraer_payload_fichas_bulk_desde_json(request)
    if error:
        return error

    recurso_ids = [
        item.get("recurso_id")
        for item in fichas_payload
        if isinstance(item, dict) and type(item.get("recurso_id")) is int
    ]
    recursos_por_id = {
        recurso.id: recurso
        for recurso in Recurso.objects.filter(id__in=recurso_ids)
    }
    matrices_por_recurso_id = {
        matriz.recurso_id: matriz
        for matriz in MatrizNaveRecurso.objects.filter(
            nave=periodo.nave,
            es_visible=True,
            recurso_id__in=recurso_ids,
            recurso__periodicidad_id=periodo.periodicidad_id,
        )
    }
    fichas_existentes = {
        ficha.recurso_id: ficha
        for ficha in FichaRegistro.objects.filter(
            periodo=periodo,
            recurso_id__in=recurso_ids,
        ).select_related("periodo", "recurso")
    }

    guardadas = 0
    errores = []

    for ficha_payload in fichas_payload:
        recurso_id = ficha_payload.get("recurso_id") if isinstance(ficha_payload, dict) else None
        try:
            data, mensaje_error = _validar_payload_ficha_dict(
                ficha_payload,
                require_recurso_id=True,
            )
            if mensaje_error:
                raise ValueError(mensaje_error)

            recurso_id = data["recurso_id"]
            recurso = recursos_por_id.get(recurso_id)
            if recurso is None:
                raise ValueError("Recurso no encontrado.")
            matriz = matrices_por_recurso_id.get(recurso_id)
            if matriz is None:
                raise ValueError("El recurso no está asignado a esta nave.")

            estado_operativo = data["estado_operativo"]
            if estado_operativo is None:
                estado_operativo = MotorFichas.derivar_estado_operativo_desde_checklist(
                    recurso,
                    data["payload_checklist"],
                    cantidad=matriz.cantidad,
                )

            ficha_existente = fichas_existentes.get(recurso_id)
            if ficha_existente is not None:
                ficha = MotorFichas.modificar_ficha(
                    ficha=ficha_existente,
                    usuario_modificador=request.user,
                    estado_operativo=estado_operativo,
                    observacion_general=data["observacion_general"],
                    payload_checklist=data["payload_checklist"],
                )
            else:
                ficha = MotorFichas.crear_ficha(
                    periodo=periodo,
                    recurso=recurso,
                    usuario=request.user,
                    estado_operativo=estado_operativo,
                    observacion_general=data["observacion_general"],
                    payload_checklist=data["payload_checklist"],
                )

            fichas_existentes[recurso_id] = ficha
            guardadas += 1
        except ValueError as exc:
            logger.error(
                (
                    "api_guardar_fichas_periodo validation error "
                    "(periodo_id=%s, recurso_id=%s, user_id=%s)"
                ),
                periodo.id,
                recurso_id,
                getattr(request.user, "id", None),
                exc_info=True,
            )
            errores.append({"recurso_id": recurso_id, "error": str(exc)})
        except Exception:
            logger.error(
                (
                    "api_guardar_fichas_periodo unexpected error "
                    "(periodo_id=%s, recurso_id=%s, user_id=%s)"
                ),
                periodo.id,
                recurso_id,
                getattr(request.user, "id", None),
                exc_info=True,
            )
            errores.append(
                {
                    "recurso_id": recurso_id,
                    "error": "Error interno procesando la ficha.",
                }
            )

    return JsonResponse({"guardadas": guardadas, "errores": errores}, status=200)
