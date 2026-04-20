import operator
import logging
from datetime import timedelta
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from .models import (
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

logger = logging.getLogger(__name__)


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

    @staticmethod
    def get_periodos_abiertos_de_nave(nave):
        """Retorna queryset de PeriodoRevision abiertos de la nave, con select_related."""
        return PeriodoRevision.objects.filter(
            nave=nave,
            estado="abierto",
        ).select_related("periodicidad")

    @staticmethod
    def get_recursos_visibles_de_nave_en_periodo(nave, periodo):
        """
        Retorna queryset de MatrizNaveRecurso visibles de la nave
        cuya periodicidad coincide con la del periodo dado.
        Incluye select_related('recurso', 'recurso__proposito', 'recurso__periodicidad').
        """
        return MatrizNaveRecurso.objects.filter(
            nave=nave,
            es_visible=True,
            recurso__periodicidad_id=periodo.periodicidad_id,
        ).select_related(
            "recurso",
            "recurso__proposito",
            "recurso__periodicidad",
        )

    @staticmethod
    def get_ficha_de_periodo_y_recurso(periodo, recurso):
        """
        Retorna la FichaRegistro si existe para ese periodo+recurso, o None.
        Nunca lanza excepción — usa filter().first().
        """
        return FichaRegistro.objects.filter(
            periodo=periodo,
            recurso=recurso,
        ).first()


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
        stats = {
            'recursos_creados': 0,
            'recursos_actualizados': 0,
            'recursos_omitidos': 0,
            'recursos_con_error': 0,
        }
        recursos_aplicables = Recurso.objects.filter(
            naviera__isnull=True
        ) | Recurso.objects.filter(
            naviera=nave.naviera
        )

        for recurso in recursos_aplicables:
            try:
                with transaction.atomic():
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

                    if created:
                        stats['recursos_creados'] += 1
                        continue

                    if matriz_obj.modificado_manualmente:
                        stats['recursos_omitidos'] += 1
                        continue

                    matriz_obj.cantidad = cantidad_calc
                    matriz_obj.es_visible = visible_calc
                    matriz_obj.save(update_fields=['cantidad', 'es_visible'])
                    stats['recursos_actualizados'] += 1
            except Exception as e:
                logger.error(
                    (
                        f"Error processing recurso {recurso.id} for nave {nave.id} "
                        f"(Naviera: {nave.naviera_id}): {str(e)}"
                    ),
                    exc_info=True
                )
                stats['recursos_con_error'] += 1

        return stats


class MotorPeriodos:
    @classmethod
    def _crear_periodo_abierto(cls, nave, periodicidad, fecha_inicio):
        fecha_termino = fecha_inicio + timedelta(days=periodicidad.duracion_dias - 1)
        return PeriodoRevision.objects.create(
            nave=nave,
            periodicidad=periodicidad,
            fecha_inicio=fecha_inicio,
            fecha_termino=fecha_termino,
            estado='abierto',
        )

    @classmethod
    def _determinar_estado_cierre(cls, periodo):
        """
        Determina el estado final de un período que expiró.
        PLACEHOLDER: Siempre retorna 'vencido'.
        En el futuro evaluará si todas las fichas están completas para retornar 'cerrado'.
        """
        return 'vencido'

    @classmethod
    def sincronizar_periodos_nave(cls, nave):
        """
        Garantiza que exista un periodo abierto por periodicidad para la nave.
        Si el periodo abierto está vencido, lo marca vencido y crea uno nuevo.
        """
        stats = {
            'periodos_creados': 0,
            'periodos_vencidos': 0,
        }
        hoy = timezone.localdate()

        with transaction.atomic():
            for periodicidad in Periodicidad.objects.all():
                periodo_abierto = (
                    PeriodoRevision.objects
                    .filter(nave=nave, periodicidad=periodicidad, estado='abierto')
                    .select_related('periodicidad')
                    .order_by('-fecha_inicio', '-id')
                    .first()
                )

                if periodo_abierto is None:
                    cls._crear_periodo_abierto(nave, periodicidad, hoy)
                    stats['periodos_creados'] += 1
                    continue

                fecha_expiracion = periodo_abierto.fecha_termino + timedelta(
                    days=periodo_abierto.periodicidad.offset_dias
                )
                if fecha_expiracion < hoy:
                    periodo_abierto.estado = cls._determinar_estado_cierre(periodo_abierto)
                    periodo_abierto.save(update_fields=['estado'])
                    stats['periodos_vencidos'] += 1

                    cls._crear_periodo_abierto(nave, periodicidad, hoy)
                    stats['periodos_creados'] += 1

        return stats

    @classmethod
    def sincronizar_todas_las_naves(cls):
        stats = {
            'naves_procesadas': 0,
            'naves_con_error': 0,
            'periodos_creados': 0,
            'periodos_vencidos': 0,
        }
        naves = Nave.objects.filter(is_active=True).select_related('naviera')

        for nave in naves:
            try:
                nave_stats = cls.sincronizar_periodos_nave(nave)
                stats['naves_procesadas'] += 1
                stats['periodos_creados'] += nave_stats['periodos_creados']
                stats['periodos_vencidos'] += nave_stats['periodos_vencidos']

            except Exception as e:
                logger.error(
                    f"Error processing nave {nave.id} (Naviera: {nave.naviera_id}): {str(e)}",
                    exc_info=True
                )
                stats['naves_con_error'] += 1

        return stats


class MotorFichas:
    @classmethod
    def validar_payload_checklist(cls, recurso, payload_checklist):
        """
        Valida que el payload incluya todos los requerimientos del recurso como keys.
        Retorna (es_valido, faltantes).
        """
        requerimientos = recurso.requerimientos or []
        if not requerimientos:
            return True, []

        if not isinstance(payload_checklist, dict):
            payload_checklist = {}

        faltantes = [req for req in requerimientos if req not in payload_checklist]
        if faltantes:
            return False, faltantes
        return True, []

    @classmethod
    def crear_ficha(
        cls,
        periodo,
        recurso,
        usuario,
        estado_operativo,
        observacion_general,
        payload_checklist,
    ):
        with transaction.atomic():
            if periodo.estado != "abierto":
                raise ValueError("No se puede registrar en un período cerrado o vencido.")

            recurso_asignado = MatrizNaveRecurso.objects.filter(
                nave=periodo.nave,
                recurso=recurso,
                es_visible=True,
            ).exists()
            if not recurso_asignado:
                raise ValueError("El recurso no está asignado a esta nave.")

            es_valido, faltantes = cls.validar_payload_checklist(recurso, payload_checklist)
            if not es_valido:
                raise ValueError(f"Faltan requerimientos en el checklist: {faltantes}")

            if FichaRegistro.objects.filter(periodo=periodo, recurso=recurso).exists():
                raise ValueError(
                    "Ya existe una ficha para este recurso en este período. Use modificar_ficha()."
                )

            try:
                ficha = FichaRegistro.objects.create(
                    periodo=periodo,
                    recurso=recurso,
                    usuario=usuario,
                    estado_operativo=estado_operativo,
                    observacion_general=observacion_general,
                    payload_checklist=payload_checklist if payload_checklist is not None else {},
                )
            except IntegrityError as exc:
                raise ValueError(
                    "Ya existe una ficha para este recurso en este período. Use modificar_ficha()."
                ) from exc

            return ficha

    @classmethod
    def modificar_ficha(
        cls,
        ficha,
        usuario_modificador,
        estado_operativo,
        observacion_general,
        payload_checklist,
    ):
        with transaction.atomic():
            if ficha.periodo.estado != "abierto":
                raise ValueError("No se puede registrar en un período cerrado o vencido.")

            es_valido, faltantes = cls.validar_payload_checklist(
                ficha.recurso,
                payload_checklist,
            )
            if not es_valido:
                raise ValueError(f"Faltan requerimientos en el checklist: {faltantes}")

            ficha.estado_operativo = estado_operativo
            ficha.observacion_general = observacion_general
            ficha.payload_checklist = payload_checklist if payload_checklist is not None else {}
            ficha.modificado_por = usuario_modificador
            ficha.modificado_en = timezone.now()
            ficha.save(
                update_fields=[
                    "estado_operativo",
                    "observacion_general",
                    "payload_checklist",
                    "modificado_por",
                    "modificado_en",
                ]
            )
            return ficha
