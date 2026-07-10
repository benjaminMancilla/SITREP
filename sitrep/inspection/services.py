import bisect
import logging
from datetime import timedelta
from django.db import IntegrityError, transaction
from django.db.models import Exists, F, OuterRef
from django.utils import timezone

from sitrep.accounts.services import AccountsQueryService
from sitrep.catalog.models import Periodicidad, Recurso
from sitrep.catalog.services import CatalogRuleEngine, construir_label_requerimiento
from sitrep.fleet.models import Nave
from sitrep.fleet.services import FleetQueryService
from .models import (
    FichaRegistro,
    MatrizNaveRecurso,
    PeriodoRevision,
)

logger = logging.getLogger(__name__)

CHECKLIST_CANTIDAD_KEY = "__cantidad__"


def contar_fichas_completas_por_periodo(periodo_ids):
    """
    Retorna {periodo_id: int} con la cantidad de fichas completas por período.
    Combina una query DB con la regla de negocio _es_ficha_completa.
    """
    conteos = {periodo_id: 0 for periodo_id in periodo_ids}
    if not periodo_ids:
        return conteos

    for ficha in FichaRegistro.objects.filter(periodo_id__in=periodo_ids).select_related("recurso"):
        if MotorPeriodos._es_ficha_completa(ficha):
            conteos[ficha.periodo_id] += 1
    return conteos


class TenantQueryService:
    ESTADOS_ABIERTOS = PeriodoRevision.ESTADOS_ABIERTOS
    ESTADOS_CERRADOS = PeriodoRevision.ESTADOS_CERRADOS

    # ponytail: fleet/accounts queries delegated — callers migrate to FleetQueryService/AccountsQueryService in full segregation
    get_nave = FleetQueryService.get_nave
    get_nave_activa = FleetQueryService.get_nave_activa
    get_naves_activas = FleetQueryService.get_naves_activas
    get_naves_del_tenant = FleetQueryService.get_naves_del_tenant
    get_dispositivo = FleetQueryService.get_dispositivo
    get_dispositivos = FleetQueryService.get_dispositivos
    get_tripulacion_de_nave = FleetQueryService.get_tripulacion_de_nave
    get_tripulacion_activa_de_nave = FleetQueryService.get_tripulacion_activa_de_nave
    get_usuario_del_tenant = AccountsQueryService.get_usuario_del_tenant
    get_usuario_activo_del_tenant = AccountsQueryService.get_usuario_activo_del_tenant
    get_usuarios_del_tenant = AccountsQueryService.get_usuarios_del_tenant

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
        Estados cerrados: operativo, observado, fallido, omitido, caduco.
        Ordenados por fecha_inicio descendente.
        """
        qs = PeriodoRevision.objects.filter(
            nave=nave,
            estado__in=TenantQueryService.ESTADOS_CERRADOS,
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

    @staticmethod
    def calcular_confiabilidad_por_periodicidad(naviera, hoy):
        _umbrales = [1, 7, 30, 90, 365]
        _ventanas = [30, 30, 90, 365, 730, 1825]
        estados_vencidos = PeriodoRevision.ESTADOS_INCOMPLETOS
        periodicidad_ids = (
            PeriodoRevision.objects.filter(nave__naviera=naviera, nave__is_active=True)
            .values_list("periodicidad_id", flat=True)
            .distinct()
        )
        resultado = []
        for periodicidad in Periodicidad.objects.filter(id__in=periodicidad_ids).order_by(
            "duracion_dias", "nombre"
        ):
            ventana = _ventanas[bisect.bisect_left(_umbrales, periodicidad.duracion_dias)]
            desde = hoy - timedelta(days=ventana)
            total_cerrados = PeriodoRevision.objects.filter(
                nave__naviera=naviera,
                nave__is_active=True,
                periodicidad=periodicidad,
                estado__in=TenantQueryService.ESTADOS_CERRADOS,
                fecha_termino__gte=desde,
            ).count()
            vencidos_ventana = PeriodoRevision.objects.filter(
                nave__naviera=naviera,
                nave__is_active=True,
                periodicidad=periodicidad,
                estado__in=estados_vencidos,
                fecha_termino__gte=desde,
            ).count()
            if total_cerrados > 0:
                resultado.append({
                    "periodicidad": periodicidad,
                    "ventana_dias": ventana,
                    "total": total_cerrados,
                    "vencidos": vencidos_ventana,
                    "pct_cumplimiento": round(
                        100 * (total_cerrados - vencidos_ventana) / total_cerrados
                    ),
                })
        return resultado


class MotorReglasSITREP:
    # ponytail: evaluar_regla delegated to CatalogRuleEngine after catalog segregation
    evaluar_regla = CatalogRuleEngine.evaluar_regla

    @classmethod
    def sincronizar_matriz_nave(cls, nave, crear_nuevos=True):
        """
        Genera o actualiza la matriz de la nave a partir del catálogo único.
        El motor de reglas es la única fuente de verdad: siempre recalcula
        cantidad/es_visible, sin excepciones manuales.
        Con crear_nuevos=False solo actualiza entradas existentes (útil en señales reactivas).
        """
        stats = {
            'recursos_creados': 0,
            'recursos_actualizados': 0,
            'recursos_omitidos': 0,
            'recursos_con_error': 0,
        }

        for recurso in Recurso.objects.all():
            try:
                with transaction.atomic():
                    cantidad_calc, visible_calc = cls.evaluar_regla(nave, recurso.regla_aplicacion)

                    if not crear_nuevos:
                        updated = MatrizNaveRecurso.objects.filter(
                            nave=nave,
                            recurso=recurso,
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
                        }
                    )

                    if created:
                        stats['recursos_creados'] += 1
                        continue

                    matriz_obj.cantidad = cantidad_calc
                    matriz_obj.es_visible = visible_calc
                    matriz_obj.save(update_fields=['cantidad', 'es_visible'])
                    stats['recursos_actualizados'] += 1
            except Exception:
                logger.error(
                    "Error processing recurso %s for nave %s (Naviera: %s)",
                    recurso.id, nave.id, nave.naviera_id,
                    exc_info=True,
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

        # cantidad=0: el número no se usa acá, solo las keys de la definición.
        definicion = MotorFichas.obtener_definicion_checklist(ficha.recurso, 0, ficha=ficha)
        if not definicion:
            return True

        payload_checklist = ficha.payload_checklist or {}
        if not isinstance(payload_checklist, dict):
            return False

        for item_def in definicion:
            item = payload_checklist.get(item_def["key"])
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
            return "vencido"

        if len(fichas_completas) < total_recursos:
            return "vencido"

        return "cumplido"

    @classmethod
    def _cerrar_periodo(cls, periodo):
        matrices = MatrizNaveRecurso.objects.filter(
            nave=periodo.nave,
            recurso__periodicidad=periodo.periodicidad,
            es_visible=True,
        )
        matrices.update(
            ultimo_estado_operativo_anterior=F("ultimo_estado_operativo")
        )
        tiene_ficha_en_periodo = FichaRegistro.objects.filter(
            periodo=periodo,
            recurso=OuterRef("recurso"),
        )
        matrices.filter(es_fallo_nuevo=True).exclude(
            Exists(tiene_ficha_en_periodo)
        ).update(es_fallo_nuevo=False)
        FichaRegistro.objects.filter(periodo=periodo, estado_ficha='en_progreso').update(estado_ficha='pendiente')

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
                        # Cambio de período (uno recién nacido): recién acá se
                        # sincroniza la matriz, no en cada tick del cron.
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
                        cls._cerrar_periodo(periodo_abierto)
                        stats['periodos_vencidos'] += 1

                        MotorReglasSITREP.sincronizar_matriz_nave(nave)
                        cls._crear_periodo_abierto(nave, periodicidad, hoy)
                        stats['periodos_creados'] += 1
                        continue

                    estado_actual = cls._calcular_estado_abierto(nave, periodo_abierto)
                    if periodo_abierto.estado != estado_actual:
                        periodo_abierto.estado = estado_actual
                        periodo_abierto.save(update_fields=["estado"])
            except Exception:
                logger.error(
                    "Error processing periodicidad %s for nave %s (Naviera: %s)",
                    periodicidad.id, nave.id, nave.naviera_id,
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

            except Exception:
                logger.error(
                    "Error processing nave %s (Naviera: %s)",
                    nave.id, nave.naviera_id,
                    exc_info=True,
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
    def construir_definicion_checklist(cls, recurso, cantidad):
        """Calcula la definición del checklist a partir del catálogo EN VIVO.
        Usar solo para una ficha que todavía no existe — una ficha existente
        debe leer su definición congelada vía obtener_definicion_checklist()."""
        return [
            {
                "key": requerimiento["id"],
                "label": construir_label_requerimiento(requerimiento, cantidad),
                "synthetic": requerimiento["tipo"] != "estandar",
            }
            for requerimiento in (recurso.requerimientos or [])
        ]

    @classmethod
    def obtener_definicion_checklist(cls, recurso, cantidad, ficha=None):
        """
        Definición de checklist a usar para leer/validar una ficha.
        Si la ficha ya existe y tiene snapshot, usa ese snapshot congelado —
        así el catálogo puede cambiar sin alterar fichas ya creadas. Sin ficha
        (aún no existe) o con fichas anteriores a este campo (snapshot None),
        cae al catálogo en vivo.
        """
        if ficha is not None and ficha.definicion_checklist is not None:
            return ficha.definicion_checklist
        return cls.construir_definicion_checklist(recurso, cantidad)

    @classmethod
    def construir_checklist_items(cls, definicion, payload_checklist=None):
        payload_checklist = cls.normalizar_payload_checklist(payload_checklist)

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
    def validar_payload_checklist(cls, definicion, payload_checklist, require_cumple=False):
        """
        Evalúa si el payload incluye todos los requerimientos de la definición.
        Con require_cumple=True verifica además que cada item tenga 'cumple' con valor no nulo.
        Retorna (esta_completo, faltantes).
        """
        if not definicion:
            return True, []

        payload_checklist = cls.normalizar_payload_checklist(payload_checklist)

        if require_cumple:
            faltantes = [
                item["label"]
                for item in definicion
                if payload_checklist.get(item["key"], {}).get("cumple") is None
            ]
        else:
            faltantes = [
                item["label"]
                for item in definicion
                if item["key"] not in payload_checklist
            ]
        return not bool(faltantes), faltantes

    @classmethod
    def validar_observaciones_requerimientos(cls, definicion, payload_checklist):
        """
        Verifica que los requerimientos fallados tengan observación.
        Retorna (es_valido, lista_de_requerimientos_sin_observacion).
        """
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
    def validar_estado_operativo(cls, definicion, estado_operativo, payload_checklist):
        """
        Impide marcar un recurso como operativo si algún requerimiento no está cumplido.
        """
        payload_checklist = cls.normalizar_payload_checklist(payload_checklist)
        if estado_operativo is None:
            return True

        if estado_operativo is False:
            return True

        if not definicion:
            return True

        return all(bool(payload_checklist.get(item["key"], {}).get("cumple")) for item in definicion)

    @classmethod
    def derivar_estado_operativo_desde_checklist(cls, definicion, payload_checklist):
        """
        Deriva el estado operativo desde el checklist:
        - True si no hay requerimientos o si todos están cumplidos
        - False si al menos uno falló (aunque haya items sin responder)
        - None si aún faltan requerimientos por registrar y ninguno falló
        """
        payload_checklist = cls.normalizar_payload_checklist(payload_checklist)
        if not definicion:
            return True

        if any(
            payload_checklist.get(item["key"], {}).get("cumple") is False
            for item in definicion
        ):
            return False

        checklist_completo, _faltantes = cls.validar_payload_checklist(
            definicion, payload_checklist, require_cumple=True,
        )
        if not checklist_completo:
            return None

        return True

    @classmethod
    def calcular_estado_ficha(cls, definicion, estado_operativo, payload_checklist):
        payload = cls.normalizar_payload_checklist(payload_checklist)
        checklist_completo, _faltantes = cls.validar_payload_checklist(
            definicion, payload, require_cumple=True,
        )
        if estado_operativo is not None and checklist_completo:
            return "completa"

        hay_respuesta = any(
            isinstance(valor, dict) and valor.get("cumple") is not None
            for valor in payload.values()
        )
        if estado_operativo is None and not hay_respuesta:
            return "pendiente"

        return "en_progreso"

    @classmethod
    def _validar_payload_o_raise(cls, definicion, estado_operativo, payload_checklist_raw):
        """Normaliza y valida el payload; retorna el payload normalizado o lanza ValueError."""
        payload = cls.normalizar_payload_checklist(payload_checklist_raw)
        # La definición ya incluye el requerimiento "cantidad" si el catálogo (congelado
        # o en vivo, según corresponda) lo declara. La validación de presencia aplica
        # solo cuando estado_operativo is not None.
        es_valido, faltantes = cls.validar_payload_checklist(definicion, payload)
        if estado_operativo is True and not es_valido:
            raise ValueError(f"Faltan requerimientos en el checklist: {faltantes}")
        checklist_completo, faltantes = cls.validar_payload_checklist(definicion, payload, require_cumple=True)
        if estado_operativo is True and not checklist_completo:
            raise ValueError(f"Faltan requerimientos completos en el checklist: {faltantes}")
        obs_valido, sin_obs = cls.validar_observaciones_requerimientos(definicion, payload_checklist_raw)
        if not obs_valido:
            raise ValueError(f"Los siguientes requerimientos fallados requieren observación: {sin_obs}")
        if not cls.validar_estado_operativo(definicion, estado_operativo, payload):
            raise ValueError("No se puede marcar el recurso como operativo si faltan requerimientos por cumplir.")
        return payload

    @classmethod
    def _actualizar_estado_matriz(cls, matriz, estado_operativo):
        """Aplica las reglas de transición de estado en ultimo_estado_operativo."""
        # NULL + prev FALLO → stays FALLO; all other combinations update
        if estado_operativo is not None or matriz.ultimo_estado_operativo is not False:
            matriz.es_fallo_nuevo = (
                estado_operativo is False
                and matriz.ultimo_estado_operativo_anterior is not False
            )
            matriz.ultimo_estado_operativo = estado_operativo
            matriz.ultimo_estado_operativo_en = timezone.now()
            matriz.save(update_fields=[
                "ultimo_estado_operativo",
                "ultimo_estado_operativo_en",
                "es_fallo_nuevo",
            ])

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

            # Se congela acá, del catálogo en vivo — es la única vez que esta
            # ficha calcula su definición desde cero. De ahí en más (incluida
            # cualquier modificar_ficha futura) usa este mismo snapshot.
            definicion = cls.construir_definicion_checklist(recurso, matriz.cantidad)
            payload_checklist = cls._validar_payload_o_raise(
                definicion, estado_operativo, payload_checklist
            )

            try:
                ficha = FichaRegistro.objects.create(
                    periodo=periodo,
                    recurso=recurso,
                    usuario=usuario,
                    estado_ficha=cls.calcular_estado_ficha(definicion, estado_operativo, payload_checklist),
                    estado_operativo=estado_operativo,
                    observacion_general=observacion_general,
                    payload_checklist=payload_checklist,
                    definicion_checklist=definicion,
                )
            except IntegrityError as exc:
                raise ValueError(
                    "Ya existe una ficha para este recurso en este período. Use modificar_ficha()."
                ) from exc

            cls._actualizar_estado_matriz(matriz, estado_operativo)
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

            # Usa el snapshot congelado al crear la ficha — nunca recalcula desde
            # el catálogo en vivo, así el catálogo puede cambiar mientras la ficha
            # sigue abierta sin alterar qué se le exige. Fichas anteriores a este
            # campo (definicion_checklist=None) se "gradúan" acá: calculan desde
            # el catálogo en vivo una vez más y de ahí quedan congeladas también.
            definicion = cls.obtener_definicion_checklist(ficha.recurso, matriz.cantidad, ficha=ficha)
            payload_checklist = cls._validar_payload_o_raise(
                definicion, estado_operativo, payload_checklist
            )

            ficha.estado_ficha = cls.calcular_estado_ficha(
                definicion, estado_operativo, payload_checklist,
            )
            ficha.estado_operativo = estado_operativo
            ficha.observacion_general = observacion_general
            ficha.payload_checklist = payload_checklist
            ficha.definicion_checklist = definicion
            ficha.modificado_por = usuario_modificador
            ficha.modificado_en = timezone.now()
            ficha.save(
                update_fields=[
                    "estado_ficha",
                    "estado_operativo",
                    "observacion_general",
                    "payload_checklist",
                    "definicion_checklist",
                    "modificado_por",
                    "modificado_en",
                ]
            )

            cls._actualizar_estado_matriz(matriz, estado_operativo)
            MotorPeriodos.sincronizar_estado_periodo_abierto(ficha.periodo)
            return ficha
