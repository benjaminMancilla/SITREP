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
