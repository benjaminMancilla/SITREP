import operator
from django.db import transaction
from django.http import Http404

from .models import (
    Dispositivo,
    MatrizNaveRecurso,
    Nave,
    Recurso,
    Tripulacion,
    Usuario,
)


class TenantQueryService:
    @staticmethod
    def get_nave(naviera, nave_id):
        """Retorna la nave si pertenece al tenant. Http404 si no existe o es de otro tenant."""
        try:
            return Nave.objects.get(id=nave_id, naviera=naviera)
        except Nave.DoesNotExist as exc:
            raise Http404("Recurso no encontrado.") from exc

    @staticmethod
    def get_nave_activa(naviera, nave_id):
        """Retorna la nave activa si pertenece al tenant. Http404 si está inactiva o no existe."""
        nave = TenantQueryService.get_nave(naviera, nave_id)
        if not nave.is_active:
            raise Http404("Recurso no encontrado.")
        return nave

    @staticmethod
    def get_dispositivo(naviera, dispositivo_id):
        """Retorna el dispositivo si pertenece al tenant. Http404 si no."""
        try:
            return Dispositivo.objects.get(id=dispositivo_id, naviera=naviera)
        except Dispositivo.DoesNotExist as exc:
            raise Http404("Recurso no encontrado.") from exc

    @staticmethod
    def get_naves_activas(naviera):
        """Retorna queryset de naves activas del tenant."""
        return Nave.objects.filter(naviera=naviera, is_active=True)

    @staticmethod
    def get_naves_del_tenant(naviera):
        """Retorna queryset de todas las naves del tenant (activas e inactivas)."""
        return Nave.objects.filter(naviera=naviera).order_by("is_active", "nombre")

    @staticmethod
    def get_dispositivos(naviera):
        """Retorna queryset de dispositivos del tenant con select_related('nave')."""
        return Dispositivo.objects.filter(naviera=naviera).select_related("nave")

    @staticmethod
    def get_usuario_del_tenant(naviera, usuario_id):
        """Retorna el usuario si pertenece al tenant. Http404 si no."""
        try:
            return Usuario.objects.get(id=usuario_id, naviera=naviera)
        except Usuario.DoesNotExist as exc:
            raise Http404("Recurso no encontrado.") from exc

    @staticmethod
    def get_usuario_activo_del_tenant(naviera, usuario_id):
        """Retorna usuario activo del tenant. Http404 si está inactivo o no existe."""
        usuario = TenantQueryService.get_usuario_del_tenant(naviera, usuario_id)
        if not usuario.is_active:
            raise Http404("Recurso no encontrado.")
        return usuario

    @staticmethod
    def get_usuarios_del_tenant(naviera):
        """Retorna queryset de usuarios activos del tenant, excluyendo superusuarios."""
        return Usuario.objects.filter(naviera=naviera, is_active=True, is_superuser=False)

    @staticmethod
    def get_tripulacion_de_nave(naviera, nave_id):
        """Retorna queryset de tripulantes de una nave, validando que la nave sea del tenant."""
        nave = TenantQueryService.get_nave_activa(naviera, nave_id)
        return Tripulacion.objects.filter(nave=nave)

    @staticmethod
    def get_tripulacion_activa_de_nave(naviera, nave_id):
        """Retorna queryset de Tripulacion de una nave del tenant, con select_related('usuario')."""
        nave = TenantQueryService.get_nave_activa(naviera, nave_id)
        return Tripulacion.objects.filter(
            nave=nave,
            usuario__is_active=True,
        ).select_related("usuario")


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
