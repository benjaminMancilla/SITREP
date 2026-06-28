"""
Capa de presentación.

Traduce resultados de servicios/repositorios a la forma exacta que necesita
el template o el JSON de Alpine. No decide reglas de negocio. Cuando necesita
datos de DB los pide a través de repositories o services — nunca ejecuta
Model.objects directamente.
"""
import bisect
import json
import re
from datetime import date, datetime

from django.utils import timezone

from .repositories import (
    get_brutos_urgencia,
    get_fichas_de_recursos_en_periodo,
    get_ultimas_fichas_fallidas,
)
from .services import MotorFichas, MotorPeriodos, TenantQueryService

# ---------------------------------------------------------------------------
# Constantes de confiabilidad (regla de negocio de presentación de ventanas)
# ---------------------------------------------------------------------------
_CONFIABILIDAD_UMBRALES = [1, 7, 30, 90, 365]
_CONFIABILIDAD_VENTANAS = [30, 30, 90, 365, 730, 1825]


def ventana_confiabilidad(duracion_dias):
    """Retorna la ventana de confiabilidad en días para una periodicidad."""
    indice = bisect.bisect_left(_CONFIABILIDAD_UMBRALES, duracion_dias)
    return _CONFIABILIDAD_VENTANAS[indice]


# ---------------------------------------------------------------------------
# Formateo de datos
# ---------------------------------------------------------------------------

def nombre_usuario_display(usuario):
    if not usuario:
        return ""
    nombre_completo = f"{usuario.first_name} {usuario.last_name}".strip()
    return nombre_completo or usuario.rut


def formatear_tiempo_transcurrido_es(fecha, ahora=None):
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


# ---------------------------------------------------------------------------
# Cálculos de período
# ---------------------------------------------------------------------------

def contar_fichas_completas(fichas):
    return sum(1 for ficha in fichas if MotorPeriodos._es_ficha_completa(ficha))


def calcular_urgencia(dias_restantes, duracion_total, cobertura):
    if duracion_total == 0:
        return 0.0
    dias_restantes = min(max(0, dias_restantes), duracion_total)
    tiempo_norm = (duracion_total - dias_restantes) / duracion_total
    return round((1.0 - cobertura) * tiempo_norm, 4)


def numero_periodo(periodo, nave):
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


def etiqueta_numero_periodicidad(periodicidad):
    nombre = (periodicidad.nombre or "").strip()
    etiquetas = {
        "quincenal": "Quincena",
        "semanal": "Semana",
        "mensual": "Mes",
        "trimestral": "Trimestre",
        "anual": "Año",
    }
    return etiquetas.get(nombre.casefold(), nombre)


# ---------------------------------------------------------------------------
# Ordenamiento de recursos y áreas
# ---------------------------------------------------------------------------

def _nombre_display_area(area):
    if area is None:
        return "Sin área"
    return (area.nombre_tecnico or area.nombre or "").strip() or area.nombre


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


def _clave_orden_matriz_recurso_periodo(matriz):
    return _clave_orden_recurso(matriz.recurso)


def _ordenar_grupos_por_area(grupos_por_area):
    grupos_con_area = [g for g in grupos_por_area.values() if g["area"] is not None]
    grupos_con_area.sort(key=lambda g: _clave_orden_area(g["area"]))
    grupo_sin_area = grupos_por_area.get(None)
    if grupo_sin_area is not None:
        grupos_con_area.append(grupo_sin_area)
    return grupos_con_area


# ---------------------------------------------------------------------------
# Agrupación por área
# ---------------------------------------------------------------------------

def agrupar_recursos_por_area(recursos_lista):
    """
    Agrupa recursos_lista por área. Sin área → al final en grupo especial.
    Retorna lista de dicts: {area, nombre_display, recursos, total, con_ficha, tiene_fallo}.
    """
    grupos = {}

    for item in recursos_lista:
        area = item["recurso"].area
        area_id = area.id if area is not None else None

        if area_id not in grupos:
            grupos[area_id] = {
                "area": area,
                "nombre_display": _nombre_display_area(area),
                "recursos": [],
                "total": 0,
                "con_ficha": 0,
                "tiene_fallo": False,
            }

        grupo = grupos[area_id]
        grupo["recursos"].append(item)
        grupo["total"] += 1
        if item.get("ficha_completa"):
            grupo["con_ficha"] += 1
        if item["estado_operativo"] is False:
            grupo["tiene_fallo"] = True

    for grupo in grupos.values():
        grupo["recursos"].sort(key=lambda item: _clave_orden_recurso(item["recurso"]))

    return _ordenar_grupos_por_area(grupos)


def agrupar_registros_por_area(registros):
    """
    Agrupa registros por área. Sin área → al final.
    Retorna lista de dicts: {area, nombre_display, registros, total, con_ficha}.
    """
    grupos = {}

    for registro in registros:
        area = registro["recurso"].area
        area_id = area.id if area is not None else None

        if area_id not in grupos:
            grupos[area_id] = {
                "area": area,
                "nombre_display": _nombre_display_area(area),
                "registros": [],
                "total": 0,
                "con_ficha": 0,
            }

        grupo = grupos[area_id]
        grupo["registros"].append(registro)
        grupo["total"] += 1
        if registro.get("ficha_completa"):
            grupo["con_ficha"] += 1

    for grupo in grupos.values():
        grupo["registros"].sort(key=lambda r: _clave_orden_recurso(r["recurso"]))

    return _ordenar_grupos_por_area(grupos)


# ---------------------------------------------------------------------------
# Construcción de listas de recursos
# ---------------------------------------------------------------------------

def construir_recursos_lista_periodo(nave, periodo, slug=None, for_history=False):
    """
    Ensambla la lista de items {matriz, recurso, ficha, checklist_items, ...}
    para la ficha de un período. No toca la DB directamente.
    """
    matrices_qs = TenantQueryService.get_recursos_visibles_de_nave_en_periodo(nave, periodo)
    if for_history:
        matrices_qs = matrices_qs.filter(recurso__created_at__date__lte=periodo.fecha_termino)

    matrices = list(matrices_qs)
    matrices.sort(key=_clave_orden_matriz_recurso_periodo)

    fichas_por_recurso_id = get_fichas_de_recursos_en_periodo(
        periodo, [m.recurso_id for m in matrices]
    )

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
            "ficha_completa": ficha is not None and MotorPeriodos._es_ficha_completa(ficha),
            "estado_ficha": ficha.estado_ficha if ficha else "pendiente",
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


def construir_periodos_detalle(nave, periodos, for_history=False):
    """
    Construye la lista de dicts de detalle por período para la vista de nave.
    """
    from django.db.models import F as DjangoF

    periodos_detalle = []
    for periodo in periodos:
        fichas = list(
            TenantQueryService.get_fichas_de_periodo(periodo).order_by(
                DjangoF("recurso__area__orden").asc(nulls_last=True),
                DjangoF("recurso__area__nombre").asc(nulls_last=True),
                "recurso__nombre",
            )
        )
        matrices_qs = TenantQueryService.get_recursos_visibles_de_nave_en_periodo(nave, periodo)
        if for_history:
            matrices_qs = matrices_qs.filter(recurso__created_at__date__lte=periodo.fecha_termino)
        matrices = list(
            matrices_qs.order_by(
                DjangoF("recurso__area__orden").asc(nulls_last=True),
                DjangoF("recurso__area__nombre").asc(nulls_last=True),
                "recurso__nombre",
            )
        )

        total_recursos = len(matrices)
        fichas_count = contar_fichas_completas(fichas)
        fichas_por_recurso_id = {ficha.recurso_id: ficha for ficha in fichas}
        registros = []
        fallos_count = 0

        for matriz in matrices:
            ficha = fichas_por_recurso_id.get(matriz.recurso_id)
            if ficha is None:
                registros.append({"tipo": "pendiente", "recurso": matriz.recurso})
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

            registros.append({
                "tipo": "ficha",
                "recurso": matriz.recurso,
                "matriz": matriz,
                "ficha": ficha,
                "ficha_completa": MotorPeriodos._es_ficha_completa(ficha),
                "estado_operativo": ficha.estado_operativo,
                "checklist_items": checklist_items,
            })

        periodos_detalle.append({
            "periodo": periodo,
            "numero": numero_periodo(periodo, nave),
            "numero_label": etiqueta_numero_periodicidad(periodo.periodicidad),
            "fichas": fichas,
            "registros": registros,
            "registros_por_area": agrupar_registros_por_area(registros),
            "total_recursos": total_recursos,
            "fichas_count": fichas_count,
            "fallos_count": fallos_count,
            "has_fallos": fallos_count > 0,
            "avance_pct": int((fichas_count * 100) / total_recursos) if total_recursos else 0,
        })
    return periodos_detalle


# ---------------------------------------------------------------------------
# Tabla de urgencia
# ---------------------------------------------------------------------------

def construir_tabla_urgencia(naviera):
    """
    Construye la estructura {columns, naves} para la tabla de urgencia del dashboard.
    Delega los queries al repositorio y aplica la lógica de presentación aquí.
    """
    from django.utils.text import slugify
    from datetime import date as date_

    brutos = get_brutos_urgencia(naviera)
    if brutos is None:
        return {"columns": [], "naves": []}

    naves = brutos["naves"]
    periodos_por_clave = brutos["periodos_por_clave"]
    fichas_raw = brutos["fichas_raw"]
    totales = brutos["totales"]
    fallos = brutos["fallos"]
    fallos_nuevos = brutos["fallos_nuevos"]

    fichas_completas = {}
    for ficha in fichas_raw:
        if MotorPeriodos._es_ficha_completa(ficha):
            fichas_completas[ficha.periodo_id] = fichas_completas.get(ficha.periodo_id, 0) + 1

    periodicidades_activas = {}
    for periodo in periodos_por_clave.values():
        if periodo.estado in TenantQueryService.ESTADOS_ABIERTOS:
            periodicidades_activas[periodo.periodicidad_id] = periodo.periodicidad

    periodicidades_ordenadas = sorted(
        periodicidades_activas.values(),
        key=lambda p: (p.duracion_dias, p.nombre.lower(), p.id),
    )

    keys_por_periodicidad = {}
    used_keys = set()
    columns = []
    for periodicidad in periodicidades_ordenadas:
        key_source = getattr(periodicidad, "nombre_tecnico", None) or periodicidad.nombre
        base_key = slugify(key_source).replace("-", "_") or f"periodicidad_{periodicidad.id}"
        key = base_key if base_key not in used_keys else f"{base_key}_{periodicidad.id}"
        used_keys.add(key)
        keys_por_periodicidad[periodicidad.id] = key
        columns.append({"key": key, "label": periodicidad.nombre})

    periodicidad_ids_activas = {p.id for p in periodicidades_ordenadas}
    hoy = date_.today()
    naves_data = []

    for nave in naves:
        periodos_nave = {col["key"]: None for col in columns}

        for periodicidad_id in periodicidad_ids_activas:
            periodo = periodos_por_clave.get((nave.id, periodicidad_id))
            if periodo is None:
                continue

            total_recursos = totales.get((nave.id, periodicidad_id), 0)
            fichas_ok = fichas_completas.get(periodo.id, 0)
            cobertura = (
                1.0 if total_recursos == 0
                else min(1.0, round(fichas_ok / total_recursos, 4))
            )
            es_abierto = periodo.estado in TenantQueryService.ESTADOS_ABIERTOS
            dias_restantes = max(0, (periodo.fecha_termino - hoy).days) if es_abierto else 0
            duracion_total = periodo.periodicidad.duracion_dias or 0
            key = keys_por_periodicidad[periodicidad_id]

            periodos_nave[key] = {
                "estado": "en_curso" if es_abierto else periodo.estado,
                "urgencia": (
                    calcular_urgencia(dias_restantes, duracion_total, cobertura)
                    if es_abierto else None
                ),
                "cobertura": cobertura,
                "dias_restantes": dias_restantes,
                "duracion_total": duracion_total,
                "fallos": fallos.get((nave.id, periodicidad_id), 0),
                "fallos_nuevos": fallos_nuevos.get((nave.id, periodicidad_id), 0),
                "fecha_cierre": (
                    None if es_abierto else periodo.fecha_termino.strftime("%d/%m/%Y")
                ),
            }

        naves_data.append({
            "id": nave.id,
            "nombre": nave.nombre,
            "matricula": nave.matricula,
            "periodos": periodos_nave,
        })

    return {"columns": columns, "naves": naves_data}


# ---------------------------------------------------------------------------
# Enriquecimiento de fallos
# ---------------------------------------------------------------------------

def adjuntar_detalle_a_fallos(fallos, naviera):
    """
    Enriquece in-place cada objeto fallo con atributos de presentación:
    tiempo_desde_display, ficha_detalle, ficha_usuario_display,
    ficha_evento_en, ficha_observacion_general, checklist_fallido.
    """
    if not fallos:
        return

    ahora = timezone.now()
    nave_ids = {fallo.nave_id for fallo in fallos}
    recurso_ids = {fallo.recurso_id for fallo in fallos}
    ultimas_fichas = get_ultimas_fichas_fallidas(naviera, nave_ids, recurso_ids)

    for fallo in fallos:
        fallo.tiempo_desde_display = formatear_tiempo_transcurrido_es(
            fallo.ultimo_estado_operativo_en,
            ahora=ahora,
        )
        ficha = ultimas_fichas.get((fallo.nave_id, fallo.recurso_id))
        fallo.ficha_detalle = ficha
        fallo.ficha_usuario_display = nombre_usuario_display(
            (ficha.modificado_por or ficha.usuario) if ficha else None
        )
        fallo.ficha_evento_en = (
            ficha.modificado_en or ficha.fecha_revision if ficha else None
        )
        fallo.ficha_observacion_general = (
            (ficha.observacion_general or "").strip() if ficha else ""
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
            item for item in checklist_items if item["checked"] is False
        ]


# ---------------------------------------------------------------------------
# JSON de período anterior (para Alpine/JS)
# ---------------------------------------------------------------------------

def construir_periodo_anterior_json(ficha_anterior, checklist_items):
    """
    Retorna la cadena JSON del período anterior para inyectar en el template.
    Compatible con el formato esperado por Alpine.
    """
    for checklist_item in checklist_items:
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

    return json.dumps(
        {
            "obsGeneral": ficha_anterior["observacion_general"] if ficha_anterior else "",
            "checklist": {
                item["key"]: item["periodo_anterior"] for item in checklist_items
            },
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")
