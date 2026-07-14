import operator

from django.db import transaction

from .models import Area, CatalogoVersion, Periodicidad, Proposito, Recurso


class CatalogRuleEngine:
    """
    Motor determinista para evaluar atributos físicos de naves contra contratos JSONB.
    Función pura: no depende de modelos de inspection.
    """

    OPERADORES = {
        '<': operator.lt,
        '<=': operator.le,
        '==': operator.eq,
        '>=': operator.ge,
        '>': operator.gt,
    }

    @classmethod
    def evaluar_regla(cls, nave, regla_json) -> tuple:
        """
        Evalúa una regla JSON contra los atributos físicos de una nave.
        Retorna (cantidad_calculada, es_visible_calculado).
        """
        if not regla_json:
            return 0, True

        version = regla_json.get('version', 1)
        evaluador = _EVALUADORES_DE_REGLA.get(version)
        if evaluador is None:
            # versión que este motor no reconoce (ej. escrita por una
            # versión futura de la app) — no se arriesga a interpretar un schema
            # que no entiende, cae al mismo fallback seguro que "sin regla".
            return 0, True
        return evaluador(nave, regla_json)

    @classmethod
    def _evaluar_v1(cls, nave, regla_json) -> tuple:
        atributo = regla_json.get('atributo')
        valor_nave = getattr(nave, atributo, None)

        if valor_nave is None:
            return (regla_json.get('fallback_cantidad', 0), regla_json.get('fallback_visible', False))

        for condicion in regla_json.get('condiciones', []):
            func_op = cls.OPERADORES.get(condicion.get('operador'))
            valor_regla = condicion.get('valor')

            try:
                valor_nave_casteado = type(valor_regla)(valor_nave)
            except (ValueError, TypeError):
                continue

            if func_op and func_op(valor_nave_casteado, valor_regla):
                return (condicion.get('resultado_cantidad', 0), condicion.get('resultado_visible', False))

        return (regla_json.get('fallback_cantidad', 0), regla_json.get('fallback_visible', False))


# Dispatch por versión de regla_aplicacion. Filas sin "version" se tratan como
# v1 (regla_json.get('version', 1) arriba). Una v2 nueva = un método
# _evaluar_v2 + una entrada acá, sin tocar ni arriesgar romper las filas v1
# existentes.
_EVALUADORES_DE_REGLA = {
    1: CatalogRuleEngine._evaluar_v1,
}


# Constructores de label por tipo de requerimiento especial.
# Un tipo nuevo = una entrada nueva acá. Tipos sin entrada (incluido "estandar")
# caen al texto fijo del editor — retro y forward compatible sin romper catálogos viejos.
_CONSTRUCTORES_LABEL_REQUERIMIENTO = {
    'cantidad': lambda spec, cantidad: f"Cantidad: {cantidad}",
    'condicion': lambda spec, cantidad: "Condición.",
    'empty': lambda spec, cantidad: "Verificación.",
}


def construir_label_requerimiento(spec, cantidad=None):
    """Label a mostrar en el checklist para un requerimiento del catálogo."""
    constructor = _CONSTRUCTORES_LABEL_REQUERIMIENTO.get(spec['tipo'])
    if constructor:
        return constructor(spec, cantidad)
    return spec.get('texto', '')


def requerimientos_estandar(*textos):
    """Convierte strings planos legacy a requerimientos tipados 'estandar'."""
    return [{'id': texto, 'tipo': 'estandar', 'texto': texto} for texto in textos]


class CatalogoResolver:
    """Resuelve qué filas de Recurso aplican efectivamente a una nave, componiendo
    capas nave > naviera > central (o solo nave+naviera si catalogo_independiente
    aplica). No modifica nada — función de lectura pura sobre el estado guardado."""

    @classmethod
    def _independiente(cls, nave):
        return bool(nave.catalogo_independiente or nave.naviera.catalogo_independiente)

    @classmethod
    def filas_vigentes_por_lineage(cls, queryset, numero_maximo=None):
        """De un queryset de Recurso (ya filtrado a UN scope), retorna
        {raiz_id: Recurso|None} — la fila de mayor 'numero' por lineage
        (None si esa cabeza tiene activo=False, i.e. lineage removida en este scope).
        numero_maximo: tope de catalogo_version.numero para reconstrucción histórica;
        None = usar la cabeza viva."""
        if numero_maximo is not None:
            queryset = queryset.filter(catalogo_version__numero__lte=numero_maximo)
        filas = queryset.select_related('linaje_raiz', 'catalogo_version').order_by(
            '-catalogo_version__numero', '-id'
        )
        vistos = {}
        for fila in filas:
            raiz_id = fila.linaje_raiz_id or fila.id
            if raiz_id not in vistos:
                vistos[raiz_id] = fila if fila.activo else None
        return vistos

    @classmethod
    def catalogo_efectivo(cls, nave, *, pin_central=None, pin_naviera=None, pin_nave=None):
        """Lista de Recurso activos y efectivos para `nave`. pin_* = numero tope
        de CatalogoVersion para esa capa (None = capa viva)."""
        naviera = nave.naviera
        independiente = cls._independiente(nave)

        capas_ordenadas = [
            (Recurso.objects.filter(naviera=naviera, nave=nave), pin_nave),
            (Recurso.objects.filter(naviera=naviera, nave__isnull=True), pin_naviera),
        ]
        if not independiente:
            capas_ordenadas.append(
                (Recurso.objects.filter(naviera__isnull=True, nave__isnull=True), pin_central)
            )

        resultado = {}
        for queryset, pin in capas_ordenadas:
            for raiz_id, fila in cls.filas_vigentes_por_lineage(queryset, pin).items():
                if raiz_id in resultado:
                    continue
                resultado[raiz_id] = fila

        return [fila for fila in resultado.values() if fila is not None]

    @classmethod
    def versiones_vigentes(cls, nave):
        """CatalogoVersion actual (cabeza) por capa aplicable a `nave` — usado por
        MotorPeriodos para pinnear qué versión produjo cada PeriodoRevision."""
        naviera = nave.naviera
        independiente = cls._independiente(nave)
        return {
            'central': (
                None if independiente else
                CatalogoVersion.objects.filter(naviera__isnull=True, nave__isnull=True).order_by('-numero').first()
            ),
            'naviera': CatalogoVersion.objects.filter(naviera=naviera, nave__isnull=True).order_by('-numero').first(),
            'nave': CatalogoVersion.objects.filter(nave=nave).order_by('-numero').first(),
        }


_CAMPOS_COPIABLES = (
    'proposito_id', 'periodicidad_id', 'area_id', 'nombre', 'codigo',
    'descripcion', 'requerimientos', 'regla_aplicacion', 'activo',
)


class CatalogoEditorService:
    """Capa de escritura versionada. Nunca hace UPDATE in-place sobre Recurso:
    cada edición/override/rollback es una fila nueva en la misma lineage."""

    @classmethod
    def _fila_desde_base(cls, *, version, base, naviera, nave, cambios):
        campos = {campo: getattr(base, campo) for campo in _CAMPOS_COPIABLES} if base else {}
        campos.update(cambios)
        campos['naviera'] = naviera
        campos['nave'] = nave
        campos['catalogo_version'] = version
        campos['linaje_raiz_id'] = (base.linaje_raiz_id or base.id) if base is not None else None
        return Recurso.objects.create(**campos)

    @classmethod
    def publicar(cls, *, naviera=None, nave=None, creado_por=None, nota="", filas):
        """filas: [{'base': Recurso|None, 'cambios': dict}, ...]. Crea UNA
        CatalogoVersion nueva para (naviera, nave) y una fila Recurso por
        elemento, todo atómico. `base=None` = recurso totalmente nuevo
        (cambios debe traer todos los campos obligatorios)."""
        with transaction.atomic():
            version = CatalogoVersion.crear_para_scope(
                naviera=naviera, nave=nave, creado_por=creado_por, nota=nota,
            )
            creadas = [
                cls._fila_desde_base(
                    version=version, base=f.get('base'),
                    naviera=naviera, nave=nave, cambios=f.get('cambios', {}),
                )
                for f in filas
            ]
            return version, creadas

    @classmethod
    def revertir_a_version(cls, *, naviera=None, nave=None, numero_objetivo, creado_por=None, nota=""):
        """Restaura el scope (naviera, nave) al estado que tenía en numero_objetivo,
        creando una NUEVA CatalogoVersion + filas Recurso copiadas de ese estado
        histórico (incluido activo=False donde corresponda). Nunca borra ni
        modifica historia — el rollback es, en sí mismo, un commit hacia adelante."""
        # No usamos CatalogoResolver.filas_vigentes_por_lineage acá: ese método
        # retorna None para lineages tombstoneadas (activo=False), pensado para
        # "ocultar del catalogo_efectivo" — pero un rollback necesita la fila
        # real de esas lineages para poder copiarla adelante con activo=False,
        # no descartarla. Se resuelve la cabeza histórica directamente.
        queryset = Recurso.objects.filter(naviera=naviera, nave=nave).filter(
            catalogo_version__numero__lte=numero_objetivo
        ).select_related('linaje_raiz', 'catalogo_version').order_by('-catalogo_version__numero', '-id')
        cabezas_por_lineage = {}
        for fila in queryset:
            raiz_id = fila.linaje_raiz_id or fila.id
            if raiz_id not in cabezas_por_lineage:
                cabezas_por_lineage[raiz_id] = fila
        specs = [{'base': fila, 'cambios': {}} for fila in cabezas_por_lineage.values()]
        return cls.publicar(
            naviera=naviera, nave=nave, creado_por=creado_por,
            nota=nota or f"Rollback a versión {numero_objetivo}",
            filas=specs,
        )


def importar_version_completa_central(json_data, *, creado_por=None, nota="", dry_run=False):
    """
    Reemplaza la versión central completa del catálogo a partir de un JSON
    externo: en un solo commit (una CatalogoVersion central), tombstonea
    TODO lo que hoy está activo en central y publica el JSON entero como
    lineages nuevas. Pensado para una carga masiva única — ver
    inspection/management/commands/load_recursos.py para altas
    incrementales idempotentes, que es un caso de uso distinto y no toca
    esto.

    Formato esperado de json_data (lista de grupos, cada uno área+periodicidad
    +propósito con sus recursos):

        [
          {
            "area": "Salvamento",
            "periodicidad": "Semanal",
            "proposito": "MATERIAL DE SEGURIDAD",
            "recursos": [
              {
                "nombre": "Chaleco Salvavidas",
                "codigo": "3.3-Q",
                "descripcion": "...",
                "requerimientos": ["Vigencia", "Talla correcta"],
                "regla_aplicacion": null
              }
            ]
          }
        ]

    - "periodicidad" debe existir ya (créala en el admin antes de importar).
    - "proposito" se infiere de "SEGURIDAD"/"OPERACIONAL" en el texto (igual
      que load_recursos); "area" se crea si no existe.
    - "requerimientos" acepta lista de strings simples (se convierten con
      requerimientos_estandar) o ya en formato tipado
      ({"id", "tipo", "texto"}) si necesitas "condicion"/"cantidad".
    - "regla_aplicacion" es opcional (mismo schema que CatalogRuleEngine).
    - "codigo"/"descripcion" son opcionales.

    Validación primero, escritura después: si CUALQUIER grupo/recurso falla
    al parsear, no se escribe nada — se retorna resumen['errores'] con todo
    lo encontrado. No es best-effort como load_recursos: un reemplazo total
    a medias es peor que no reemplazar nada.

    ponytail: el "reemplazo" es ciego — no intenta emparejar recursos nuevos
    contra los viejos por nombre/código, simplemente tombstonea todo lo
    activo y publica el JSON como raíces nuevas. Correcto para un reset
    pre-producción (todavía no hay historial operativo real detrás de esas
    lineages). Si este comando se reutiliza con el catálogo ya en producción
    real, hay que reemplazar esto por un diff real (emparejar por 'codigo')
    para no perder la lineage de recursos que ya tienen historial operativo.
    """
    errores = []
    filas_nuevas = []
    resumen = {"grupos": 0, "recursos_nuevos": 0, "recursos_desactivados": 0, "errores": []}

    for i, grupo in enumerate(json_data):
        contexto = f"grupo #{i} (area={grupo.get('area')!r})"
        try:
            nombre_area = grupo["area"]
            nombre_periodicidad = grupo["periodicidad"]
            proposito_str = grupo["proposito"]
            recursos_grupo = grupo["recursos"]
        except KeyError as e:
            errores.append(f"{contexto}: falta el campo {e}")
            continue

        try:
            periodicidad = Periodicidad.objects.get(nombre__iexact=nombre_periodicidad)
        except Periodicidad.DoesNotExist:
            errores.append(
                f"{contexto}: periodicidad {nombre_periodicidad!r} no existe, "
                "créala en el admin antes de importar"
            )
            continue

        proposito_upper = proposito_str.upper()
        if "SEGURIDAD" in proposito_upper:
            categoria = "Seguridad"
        elif "OPERACIONAL" in proposito_upper:
            categoria = "Operacional"
        else:
            errores.append(
                f"{contexto}: no se pudo inferir categoría de propósito desde "
                f"{proposito_str!r} (se espera 'SEGURIDAD' u 'OPERACIONAL' en el texto)"
            )
            continue

        if not dry_run:
            area, _ = Area.objects.get_or_create(nombre=nombre_area, defaults={"nombre_tecnico": nombre_area})
            proposito, _ = Proposito.objects.get_or_create(
                categoria=categoria, tipo="Material", defaults={"nombre": proposito_str.title()},
            )
            area_id, proposito_id = area.id, proposito.id
        else:
            area_id = proposito_id = None  # dry-run no publica nada, no hace falta el id real

        resumen["grupos"] += 1

        for j, r in enumerate(recursos_grupo):
            contexto_r = f"{contexto} / recurso #{j} ({r.get('nombre')!r})"
            try:
                nombre = r["nombre"]
                requerimientos = r["requerimientos"]
            except KeyError as e:
                errores.append(f"{contexto_r}: falta el campo {e}")
                continue

            if requerimientos and isinstance(requerimientos[0], str):
                requerimientos = requerimientos_estandar(*requerimientos)

            filas_nuevas.append({
                "base": None,
                "cambios": {
                    "nombre": nombre, "codigo": r.get("codigo"), "descripcion": r.get("descripcion"),
                    "area_id": area_id, "periodicidad_id": periodicidad.id, "proposito_id": proposito_id,
                    "requerimientos": requerimientos, "regla_aplicacion": r.get("regla_aplicacion"),
                    "activo": True,
                },
            })
            resumen["recursos_nuevos"] += 1

    if errores:
        resumen["errores"] = errores
        return resumen

    central_qs = Recurso.objects.filter(naviera__isnull=True, nave__isnull=True)
    cabezas_activas = [
        fila for fila in CatalogoResolver.filas_vigentes_por_lineage(central_qs).values() if fila is not None
    ]
    resumen["recursos_desactivados"] = len(cabezas_activas)

    if dry_run:
        return resumen

    filas = [{"base": cabeza, "cambios": {"activo": False}} for cabeza in cabezas_activas] + filas_nuevas
    version, _ = CatalogoEditorService.publicar(
        naviera=None, nave=None, creado_por=creado_por,
        nota=nota or "Importación de versión completa del catálogo central",
        filas=filas,
    )
    resumen["version_numero"] = version.numero
    return resumen
