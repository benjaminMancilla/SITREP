import operator
from django.db import transaction
from .models import Recurso, MatrizNaveRecurso

class MotorReglasSITREP:
    """
    Motor determinista para evaluar atributos físicos de naves contra contratos JSONB.
    """
    
    OPERADORES = {
        '<': operator.lt,
        '<=': operator.le,
        '==': operator.eq,
        '>=': operator.ge,
        '>': operator.gt,
    }
    
    @classmethod
    def evaluar_regla(cls, nave, regla_json):
        """
        Evalúa una regla JSON contra los atributos físicos de una nave.
        Retorna (cantidad_calculada, es_visible_calculado)
        """
        if not regla_json:
            return 0, True  # Fallback default

        atributo = regla_json.get('atributo')
        valor_nave = getattr(nave, atributo, None)
        
        if valor_nave is None: # Fallback definido en la regla si no hay valor
            return (regla_json.get('fallback_cantidad', 0), regla_json.get('fallback_visible', False))
        
        # Evaluamos cada condición en orden
        for condicion in regla_json.get('condiciones', []): 
            func_op = cls.OPERADORES.get(condicion.get('operador'))
            valor_regla = condicion.get('valor')
            
            try:
                valor_nave_casteado = type(valor_regla)(valor_nave)
            except (ValueError, TypeError):
                continue
            
            # Si la condición se cumple, retornamos el resultado definido en esa condición
            if func_op and func_op(valor_nave_casteado, valor_regla):
                return (condicion.get('resultado_cantidad', 0), condicion.get('resultado_visible', False))
            
        # Fallback si ninguna condición se cumple
        return (regla_json.get('fallback_cantidad', 0), regla_json.get('fallback_visible', False))
    
    @classmethod
    def sincronizar_matriz_nave(cls, nave):
        """
        Genera o actualiza la matriz de la nave.
        RESPETA LA BANDERA DE AUDITORÍA (modificado_manualmente).
        """
        recursos_aplicables = Recurso.objects.filter(
            naviera__isnull=True
        ) | Recurso.objects.filter(
            naviera=nave.naviera
        )

        with transaction.atomic():
            for recurso in recursos_aplicables:
                cantidad_calc, visible_calc = cls.evaluar_regla(nave, recurso.regla_aplicacion)
                
                matriz_obj, created = MatrizNaveRecurso.objects.get_or_create(
                    nave=nave,
                    recurso=recurso,
                    defaults={
                        'cantidad': cantidad_calc,
                        'es_visible': visible_calc,
                        'modificado_manualmente': False
                    }
                )

                if not created and not matriz_obj.modificado_manualmente:
                    matriz_obj.cantidad = cantidad_calc
                    matriz_obj.es_visible = visible_calc
                    matriz_obj.save(update_fields=['cantidad', 'es_visible'])