import bisect
import re


# ---------------------------------------------------------------------------
# Constantes de confiabilidad
# ---------------------------------------------------------------------------
_CONFIABILIDAD_UMBRALES = [1, 7, 30, 90, 365]
_CONFIABILIDAD_VENTANAS = [30, 30, 90, 365, 730, 1825]


def ventana_confiabilidad(duracion_dias):
    indice = bisect.bisect_left(_CONFIABILIDAD_UMBRALES, duracion_dias)
    return _CONFIABILIDAD_VENTANAS[indice]


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
# Colores PDF por área
# ---------------------------------------------------------------------------

_AREA_COLORS = {
    "salvamento":    {"bg": "#854d0e", "text": "#ffffff", "bg_light": "#fef9c3"},
    "incendio":      {"bg": "#be123c", "text": "#ffffff", "bg_light": "#fff1f2"},
    "inundacion":    {"bg": "#a21caf", "text": "#ffffff", "bg_light": "#fdf4ff"},
    "gobierno":      {"bg": "#b45309", "text": "#ffffff", "bg_light": "#fffbeb"},
    "contaminacion": {"bg": "#475569", "text": "#ffffff", "bg_light": "#f8fafc"},
    "navegacion":    {"bg": "#0369a1", "text": "#ffffff", "bg_light": "#f0f9ff"},
    "maquinas":      {"bg": "#c2410c", "text": "#ffffff", "bg_light": "#fff7ed"},
    "telecom":       {"bg": "#047857", "text": "#ffffff", "bg_light": "#f0fdf4"},
    "general":       {"bg": "#475569", "text": "#ffffff", "bg_light": "#f8fafc"},
}
_AREA_COLOR_DEFAULT = {"bg": "#0f2d4a", "text": "#ffffff"}


def adjuntar_colores_pdf(areas_grupos):
    for grupo in areas_grupos:
        area = grupo.get("area")
        token = area.token_color if area else None
        grupo["area_color"] = _AREA_COLORS.get(token, _AREA_COLOR_DEFAULT)
