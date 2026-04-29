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

CHECKLIST_CANTIDAD_KEY = "__cantidad__"


class TenantQueryService:
    ESTADOS_ABIERTOS = {"pendiente", "en_proceso"}

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
            estado__in=TenantQueryService.ESTADOS_ABIERTOS,
        ).select_related("periodicidad")

    @staticmethod
    def get_periodos_historial_de_nave(
        nave,
        fecha_desde=None,
        fecha_hasta=None,
        estado=None,
        periodicidad_id=None,
    ):
        """
        Retorna queryset de PeriodoRevision cerrados de una nave con filtros opcionales.
        Estados cerrados: conforme, observado, fallido, omitido, caduco.
        Ordenados por fecha_inicio descendente.
        """
        ESTADOS_CERRADOS = {"conforme", "observado", "fallido", "omitido", "caduco"}
        qs = PeriodoRevision.objects.filter(
            nave=nave,
            estado__in=ESTADOS_CERRADOS,
        ).select_related("periodicidad")

        if fecha_desde:
            qs = qs.filter(fecha_inicio__gte=fecha_desde)
        if fecha_hasta:
            qs = qs.filter(fecha_termino__lte=fecha_hasta)
        if estado:
            qs = qs.filter(estado=estado)
        if periodicidad_id:
            qs = qs.filter(periodicidad_id=periodicidad_id)

        return qs.order_by("-fecha_inicio")

    @staticmethod
    def get_periodos_de_nave(nave, estado=None):
        """
        Retorna queryset de PeriodoRevision de la nave.
        Si estado es None, retorna todos. Si no, filtra por estado.
        Ordenados por fecha_inicio descendente.
        """
        queryset = PeriodoRevision.objects.filter(nave=nave)
        if estado is not None:
            queryset = queryset.filter(estado=estado)
        return queryset.order_by("-fecha_inicio")

    @staticmethod
    def get_fichas_de_periodo(periodo):
        """
        Retorna queryset de FichaRegistro de un período,
        con select_related('recurso', 'usuario', 'modificado_por').
        """
        return FichaRegistro.objects.filter(periodo=periodo).select_related(
            "recurso",
            "usuario",
            "modificado_por",
        )

    @staticmethod
    def get_recursos_visibles_de_nave_en_periodo(nave, periodo):
        """
        Retorna queryset de MatrizNaveRecurso visibles de la nave
        cuya periodicidad coincide con la del periodo dado.
        Incluye select_related(
            'recurso',
            'recurso__area',
            'recurso__proposito',
            'recurso__periodicidad',
        ).
        """
        return MatrizNaveRecurso.objects.filter(
            nave=nave,
            es_visible=True,
            recurso__periodicidad_id=periodo.periodicidad_id,
        ).select_related(
            "recurso",
            "recurso__area",
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
    def sincronizar_matriz_nave(cls, nave, solo_actualizar=False):
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

                    if solo_actualizar:
                        # Solo actualiza entradas existentes, no crea nuevas
                        updated = MatrizNaveRecurso.objects.filter(
                            nave=nave,
                            recurso=recurso,
                            modificado_manualmente=False,
                        ).update(cantidad=cantidad_calc, es_visible=visible_calc)
                        if updated:
                            stats['recursos_actualizados'] += 1
                        else:
                            stats['recursos_omitidos'] += 1
                        continue

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
            estado='pendiente',
        )

    @classmethod
    def _es_ficha_completa(cls, ficha):
        """
        Una ficha está completa cuando:
        - Todos los requerimientos del recurso tienen datos en payload_checklist
        - Cada requerimiento define 'cumple'
        - estado_operativo no es None
        """
        if ficha.estado_operativo is None:
            return False

        requerimientos = ficha.recurso.requerimientos or []
        if not requerimientos:
            return True

        payload_checklist = ficha.payload_checklist or {}
        if not isinstance(payload_checklist, dict):
            return False

        requerimientos_esperados = list(requerimientos)
        if CHECKLIST_CANTIDAD_KEY in payload_checklist:
            requerimientos_esperados.append(CHECKLIST_CANTIDAD_KEY)

        for requerimiento in requerimientos_esperados:
            item = payload_checklist.get(requerimiento)
            if not isinstance(item, dict) or "cumple" not in item:
                return False

        return True

    @classmethod
    def _calcular_estado_abierto(cls, nave, periodo):
        """
        Calcula el estado actual de un período abierto.
        Retorna 'pendiente' o 'en_proceso'.
        """
        fichas = FichaRegistro.objects.filter(periodo=periodo).select_related("recurso")
        fichas_completas = sum(1 for ficha in fichas if cls._es_ficha_completa(ficha))
        return "en_proceso" if fichas_completas >= 1 else "pendiente"

    @classmethod
    def sincronizar_estado_periodo_abierto(cls, periodo):
        if periodo.estado not in TenantQueryService.ESTADOS_ABIERTOS:
            return periodo.estado

        nuevo_estado = cls._calcular_estado_abierto(periodo.nave, periodo)
        if periodo.estado != nuevo_estado:
            periodo.estado = nuevo_estado
            periodo.save(update_fields=["estado"])
        return periodo.estado

    @classmethod
    def _determinar_estado_cierre(cls, periodo):
        """
        Determina el estado final de un período expirado usando el avance real
        de las fichas visibles para la periodicidad de la nave.
        """
        total_recursos = MatrizNaveRecurso.objects.filter(
            nave=periodo.nave,
            es_visible=True,
            recurso__periodicidad_id=periodo.periodicidad_id,
        ).count()
        fichas = list(
            FichaRegistro.objects.filter(periodo=periodo).select_related("recurso")
        )
        fichas_completas = [ficha for ficha in fichas if cls._es_ficha_completa(ficha)]

        if not fichas_completas:
            return "omitido" if not fichas else "caduco"

        if len(fichas_completas) < total_recursos:
            return "caduco"

        if len(fichas_completas) == total_recursos:
            if any(ficha.estado_operativo is False for ficha in fichas_completas):
                return "fallido"
            if any((ficha.observacion_general or "").strip() for ficha in fichas_completas):
                return "observado"
            return "conforme"

        return "caduco"

    @classmethod
    def sincronizar_periodos_nave(cls, nave):
        """
        Garantiza que exista un periodo abierto por periodicidad para la nave.
        Si el periodo abierto expiró, lo cierra según el avance real y crea uno nuevo.
        """
        stats = {
            'periodos_creados': 0,
            'periodos_vencidos': 0,
            'periodos_con_error': 0,
        }
        hoy = timezone.localdate()

        for periodicidad in Periodicidad.objects.all():
            try:
                with transaction.atomic():
                    periodo_abierto = (
                        PeriodoRevision.objects
                        .filter(
                            nave=nave,
                            periodicidad=periodicidad,
                            estado__in=TenantQueryService.ESTADOS_ABIERTOS,
                        )
                        .select_related('periodicidad')
                        .order_by('-fecha_inicio', '-id')
                        .first()
                    )

                    if periodo_abierto is None:
                        MotorReglasSITREP.sincronizar_matriz_nave(nave)
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

                        MotorReglasSITREP.sincronizar_matriz_nave(nave)
                        cls._crear_periodo_abierto(nave, periodicidad, hoy)
                        stats['periodos_creados'] += 1
                        continue

                    estado_actual = cls._calcular_estado_abierto(nave, periodo_abierto)
                    if periodo_abierto.estado != estado_actual:
                        periodo_abierto.estado = estado_actual
                        periodo_abierto.save(update_fields=["estado"])
            except Exception as e:
                logger.error(
                    (
                        f"Error processing periodicidad {periodicidad.id} for nave {nave.id} "
                        f"(Naviera: {nave.naviera_id}): {str(e)}"
                    ),
                    exc_info=True,
                )
                stats['periodos_con_error'] += 1

        return stats

    @classmethod
    def sincronizar_todas_las_naves(cls):
        stats = {
            'naves_procesadas': 0,
            'naves_con_error': 0,
            'periodos_creados': 0,
            'periodos_vencidos': 0,
            'periodos_con_error': 0,
        }
        naves = Nave.objects.filter(is_active=True).select_related('naviera')

        for nave in naves:
            try:
                nave_stats = cls.sincronizar_periodos_nave(nave)
                stats['naves_procesadas'] += 1
                stats['periodos_creados'] += nave_stats['periodos_creados']
                stats['periodos_vencidos'] += nave_stats['periodos_vencidos']
                stats['periodos_con_error'] += nave_stats['periodos_con_error']

            except Exception as e:
                logger.error(
                    f"Error processing nave {nave.id} (Naviera: {nave.naviera_id}): {str(e)}",
                    exc_info=True
                )
                stats['naves_con_error'] += 1

        return stats


class MotorFichas:
    CANTIDAD_REQUISITO_KEY = CHECKLIST_CANTIDAD_KEY

    @classmethod
    def normalizar_payload_checklist(cls, payload_checklist):
        if not isinstance(payload_checklist, dict):
            return {}

        payload_normalizado = {}
        for requerimiento, valor in payload_checklist.items():
            if isinstance(valor, dict):
                item_normalizado = dict(valor)
                if "cumple" in item_normalizado and "observacion" not in item_normalizado:
                    item_normalizado["observacion"] = ""
                payload_normalizado[requerimiento] = item_normalizado
            elif isinstance(valor, bool):
                payload_normalizado[requerimiento] = {
                    "cumple": valor,
                    "observacion": "",
                }
            else:
                payload_normalizado[requerimiento] = valor
        return payload_normalizado

    @classmethod
    def construir_definicion_checklist(
        cls,
        recurso,
        cantidad,
        incluir_requisito_cantidad=None,
    ):
        if incluir_requisito_cantidad is None:
            incluir_requisito_cantidad = cantidad > 1

        definicion = [
            {
                "key": requerimiento,
                "label": requerimiento,
                "synthetic": False,
            }
            for requerimiento in (recurso.requerimientos or [])
        ]
        if incluir_requisito_cantidad:
            definicion.append(
                {
                    "key": cls.CANTIDAD_REQUISITO_KEY,
                    "label": f"Cantidad: {cantidad}",
                    "synthetic": True,
                }
            )
        return definicion

    @classmethod
    def construir_checklist_items(
        cls,
        recurso,
        cantidad,
        payload_checklist=None,
        incluir_requisito_cantidad=None,
    ):
        payload_checklist = cls.normalizar_payload_checklist(payload_checklist)
        definicion = cls.construir_definicion_checklist(
            recurso,
            cantidad,
            incluir_requisito_cantidad=incluir_requisito_cantidad,
        )

        checklist_items = []
        for index, item_def in enumerate(definicion):
            payload_item = payload_checklist.get(item_def["key"], {})
            checked = None
            observacion = ""
            if isinstance(payload_item, dict) and "cumple" in payload_item:
                checked = payload_item.get("cumple")
                observacion = payload_item.get("observacion", "")

            checklist_items.append(
                {
                    "index": index,
                    "key": item_def["key"],
                    "label": item_def["label"],
                    "synthetic": item_def["synthetic"],
                    "checked": checked,
                    "observacion": observacion,
                }
            )

        return checklist_items

    @classmethod
    def obtener_matriz_visible_periodo(cls, periodo, recurso):
        return MatrizNaveRecurso.objects.filter(
            nave=periodo.nave,
            recurso=recurso,
            es_visible=True,
            recurso__periodicidad_id=periodo.periodicidad_id,
        ).first()

    @classmethod
    def validar_payload_checklist(cls, recurso, payload_checklist, cantidad=0):
        """
        Evalúa si el payload incluye todos los requerimientos del recurso.
        Retorna (esta_completo, faltantes).
        """
        definicion = cls.construir_definicion_checklist(recurso, cantidad)
        if not definicion:
            return True, []

        payload_checklist = cls.normalizar_payload_checklist(payload_checklist)

        faltantes = [
            item["label"]
            for item in definicion
            if item["key"] not in payload_checklist
        ]
        if faltantes:
            return False, faltantes
        return True, []

    @classmethod
    def validar_payload_checklist_completo(cls, recurso, payload_checklist, cantidad=0):
        definicion = cls.construir_definicion_checklist(recurso, cantidad)
        if not definicion:
            return True, []

        payload_checklist = cls.normalizar_payload_checklist(payload_checklist)
        faltantes = []
        for item_def in definicion:
            item = payload_checklist.get(item_def["key"])
            if not isinstance(item, dict) or "cumple" not in item:
                faltantes.append(item_def["label"])

        if faltantes:
            return False, faltantes
        return True, []

    @classmethod
    def validar_observaciones_requerimientos(cls, recurso, payload_checklist, cantidad=0):
        """
        Verifica que los requerimientos fallados tengan observación.
        Retorna (es_valido, lista_de_requerimientos_sin_observacion).
        """
        definicion = cls.construir_definicion_checklist(recurso, cantidad)
        if not definicion:
            return True, []

        payload_original = payload_checklist if isinstance(payload_checklist, dict) else {}
        payload_checklist = cls.normalizar_payload_checklist(payload_checklist)
        sin_observacion = []
        for item_def in definicion:
            item = payload_checklist.get(item_def["key"])
            if not isinstance(item, dict):
                continue
            item_original = payload_original.get(item_def["key"])

            # Compatibilidad con payloads legacy: si la clave "observacion" no venía
            # en el request original, no bloqueamos el guardado por ese motivo.
            requiere_observacion = not isinstance(item_original, dict) or "observacion" in item_original
            if (
                requiere_observacion
                and item.get("cumple") is False
                and not (item.get("observacion", "").strip())
            ):
                sin_observacion.append(item_def["label"])

        if sin_observacion:
            return False, sin_observacion
        return True, []

    @classmethod
    def validar_estado_operativo(cls, recurso, estado_operativo, payload_checklist, cantidad=0):
        """
        Impide marcar un recurso como operativo si algún requerimiento no está cumplido.
        """
        payload_checklist = cls.normalizar_payload_checklist(payload_checklist)
        if estado_operativo is None:
            return True

        if estado_operativo is False:
            return True

        definicion = cls.construir_definicion_checklist(recurso, cantidad)
        if not definicion:
            return True

        return all(bool(payload_checklist.get(item["key"], {}).get("cumple")) for item in definicion)

    @classmethod
    def derivar_estado_operativo_desde_checklist(cls, recurso, payload_checklist, cantidad=0):
        """
        Deriva el estado operativo desde el checklist:
        - True si no hay requerimientos o si todos están cumplidos
        - False si el checklist está completo y al menos uno falló
        - None si aún faltan requerimientos por registrar
        """
        payload_checklist = cls.normalizar_payload_checklist(payload_checklist)
        definicion = cls.construir_definicion_checklist(recurso, cantidad)
        if not definicion:
            return True

        checklist_completo, _faltantes = cls.validar_payload_checklist_completo(
            recurso,
            payload_checklist,
            cantidad=cantidad,
        )
        if not checklist_completo:
            return None

        if any(
            payload_checklist.get(item["key"], {}).get("cumple") is False
            for item in definicion
        ):
            return False

        if all(
            payload_checklist.get(item["key"], {}).get("cumple") is True
            for item in definicion
        ):
            return True

        return None

    @classmethod
    def calcular_estado_ficha(cls, recurso, estado_operativo, payload_checklist, cantidad=0):
        if estado_operativo is None:
            return "en_progreso"

        definicion = cls.construir_definicion_checklist(recurso, cantidad)
        if not definicion:
            return "completa"

        payload = cls.normalizar_payload_checklist(payload_checklist)
        all_complete = all(
            isinstance(payload.get(item["key"]), dict)
            and "cumple" in payload.get(item["key"], {})
            for item in definicion
        )
        return "completa" if all_complete else "en_progreso"

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
            if periodo.estado not in TenantQueryService.ESTADOS_ABIERTOS:
                raise ValueError("No se puede registrar en un período cerrado.")

            matriz = cls.obtener_matriz_visible_periodo(periodo, recurso)
            if matriz is None:
                raise ValueError("El recurso no está asignado a esta nave.")

            payload_checklist_original = payload_checklist
            payload_checklist = cls.normalizar_payload_checklist(payload_checklist)
            es_valido, faltantes = cls.validar_payload_checklist(
                recurso,
                payload_checklist,
                cantidad=matriz.cantidad,
            )
            # construir_definicion_checklist ya incluye __cantidad__ cuando cantidad > 1.
            # La validación de presencia aplica solo cuando estado_operativo is not None.
            if estado_operativo is not None and not es_valido:
                raise ValueError(f"Faltan requerimientos en el checklist: {faltantes}")
            checklist_completo, faltantes = cls.validar_payload_checklist_completo(
                recurso,
                payload_checklist,
                cantidad=matriz.cantidad,
            )
            if estado_operativo is not None and not checklist_completo:
                raise ValueError(f"Faltan requerimientos completos en el checklist: {faltantes}")
            obs_valido, sin_obs = cls.validar_observaciones_requerimientos(
                recurso,
                payload_checklist_original,
                cantidad=matriz.cantidad,
            )
            if not obs_valido:
                raise ValueError(
                    f"Los siguientes requerimientos fallados requieren observación: {sin_obs}"
                )
            if not cls.validar_estado_operativo(
                recurso,
                estado_operativo,
                payload_checklist,
                cantidad=matriz.cantidad,
            ):
                raise ValueError(
                    "No se puede marcar el recurso como operativo si faltan requerimientos por cumplir."
                )

            if FichaRegistro.objects.filter(periodo=periodo, recurso=recurso).exists():
                raise ValueError(
                    "Ya existe una ficha para este recurso en este período. Use modificar_ficha()."
                )

            try:
                ficha = FichaRegistro.objects.create(
                    periodo=periodo,
                    recurso=recurso,
                    usuario=usuario,
                    estado_ficha="en_progreso",
                    estado_operativo=estado_operativo,
                    observacion_general=observacion_general,
                    payload_checklist=payload_checklist,
                )
            except IntegrityError as exc:
                raise ValueError(
                    "Ya existe una ficha para este recurso en este período. Use modificar_ficha()."
                ) from exc

            MotorPeriodos.sincronizar_estado_periodo_abierto(periodo)
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
            if ficha.periodo.estado not in TenantQueryService.ESTADOS_ABIERTOS:
                raise ValueError("No se puede registrar en un período cerrado.")

            matriz = cls.obtener_matriz_visible_periodo(ficha.periodo, ficha.recurso)
            if matriz is None:
                raise ValueError("El recurso no está asignado a esta nave.")

            payload_checklist_original = payload_checklist
            payload_checklist = cls.normalizar_payload_checklist(payload_checklist)
            es_valido, faltantes = cls.validar_payload_checklist(
                ficha.recurso,
                payload_checklist,
                cantidad=matriz.cantidad,
            )
            # construir_definicion_checklist ya incluye __cantidad__ cuando cantidad > 1.
            # La validación de presencia aplica solo cuando estado_operativo is not None.
            if estado_operativo is not None and not es_valido:
                raise ValueError(f"Faltan requerimientos en el checklist: {faltantes}")
            checklist_completo, faltantes = cls.validar_payload_checklist_completo(
                ficha.recurso,
                payload_checklist,
                cantidad=matriz.cantidad,
            )
            if estado_operativo is not None and not checklist_completo:
                raise ValueError(f"Faltan requerimientos completos en el checklist: {faltantes}")
            obs_valido, sin_obs = cls.validar_observaciones_requerimientos(
                ficha.recurso,
                payload_checklist_original,
                cantidad=matriz.cantidad,
            )
            if not obs_valido:
                raise ValueError(
                    f"Los siguientes requerimientos fallados requieren observación: {sin_obs}"
                )
            if not cls.validar_estado_operativo(
                ficha.recurso,
                estado_operativo,
                payload_checklist,
                cantidad=matriz.cantidad,
            ):
                raise ValueError(
                    "No se puede marcar el recurso como operativo si faltan requerimientos por cumplir."
                )

            ficha.estado_ficha = cls.calcular_estado_ficha(
                recurso=ficha.recurso,
                estado_operativo=estado_operativo,
                payload_checklist=payload_checklist,
                cantidad=matriz.cantidad,
            )
            ficha.estado_operativo = estado_operativo
            ficha.observacion_general = observacion_general
            ficha.payload_checklist = payload_checklist
            ficha.modificado_por = usuario_modificador
            ficha.modificado_en = timezone.now()
            ficha.save(
                update_fields=[
                    "estado_ficha",
                    "estado_operativo",
                    "observacion_general",
                    "payload_checklist",
                    "modificado_por",
                    "modificado_en",
                ]
            )
            MotorPeriodos.sincronizar_estado_periodo_abierto(ficha.periodo)
            return ficha
