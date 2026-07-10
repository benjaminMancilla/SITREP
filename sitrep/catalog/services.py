import operator


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
