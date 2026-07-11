import operator

from django.db import transaction

from .models import CatalogoVersion, Recurso


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
