import json
import logging

from django.http import Http404, JsonResponse

from sitrep.accounts.decorators import requiere_rol, tenant_member_required
from sitrep.catalog.models import Recurso

from ..models import FichaRegistro, MatrizNaveRecurso
from .. import repositories
from ..services import TenantQueryService, MotorFichas, contar_fichas_completas_por_periodo

logger = logging.getLogger(__name__)


def _json_error(mensaje, status):
    return JsonResponse({"error": mensaje}, status=status)


def _obtener_nave_activa_desde_sesion(request):
    nave_id = request.session.get("nave_id")
    if not nave_id:
        return None, _json_error("Sesión de nave no disponible.", 403)

    try:
        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    except Http404:
        return None, _json_error("Nave no encontrada.", 404)

    return nave, None


def _cargar_payload_json(request):
    try:
        return json.loads(request.body), None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, _json_error("JSON inválido.", 400)


def _validar_payload_ficha_dict(payload, require_recurso_id=False):
    if not isinstance(payload, dict):
        return None, "La ficha debe ser un objeto JSON."

    data = {}
    if require_recurso_id:
        recurso_id = payload.get("recurso_id")
        if type(recurso_id) is not int:
            return None, "recurso_id debe ser entero."
        data["recurso_id"] = recurso_id

    estado_operativo = payload.get("estado_operativo")
    observacion_general = payload.get("observacion_general", "")
    payload_checklist = payload.get("payload_checklist", {})

    if estado_operativo is not None and type(estado_operativo) is not bool:
        return None, "estado_operativo debe ser booleano o null."
    if not isinstance(observacion_general, str):
        return None, "observacion_general debe ser texto."
    if not isinstance(payload_checklist, dict):
        return None, "payload_checklist debe ser un objeto JSON."

    data.update(
        {
            "estado_operativo": estado_operativo,
            "observacion_general": observacion_general,
            "payload_checklist": payload_checklist,
        }
    )
    return data, None


def _extraer_payload_fichas_bulk_desde_json(request):
    payload, error = _cargar_payload_json(request)
    if error:
        return None, error

    if not isinstance(payload, dict):
        return None, _json_error("El body debe ser un objeto JSON.", 400)

    fichas = payload.get("fichas")
    if not isinstance(fichas, list):
        return None, _json_error("fichas debe ser una lista.", 400)

    return fichas, None


@tenant_member_required
@requiere_rol("mar", "capitan", "tierra", "admin_naviera", "admin_sitrep")
def api_guardar_fichas_periodo(request, slug, periodo_id):
    """
    POST: recibe lista de fichas con cambios y las crea/actualiza en una transacción.
    Solo procesa los recursos incluidos en el payload — no sobreescribe lo no enviado.
    """
    if request.method != "POST":
        return _json_error("Método no permitido.", 405)

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = repositories.get_periodo_de_nave(nave, periodo_id)
    if periodo is None or periodo.estado not in TenantQueryService.ESTADOS_ABIERTOS:
        return _json_error("Período no encontrado.", 404)

    fichas_payload, error = _extraer_payload_fichas_bulk_desde_json(request)
    if error:
        return error

    recurso_ids = [
        item.get("recurso_id")
        for item in fichas_payload
        if isinstance(item, dict) and type(item.get("recurso_id")) is int
    ]
    recursos_por_id = {
        recurso.id: recurso
        for recurso in Recurso.objects.filter(id__in=recurso_ids)
    }
    matrices_por_recurso_id = {
        matriz.recurso_id: matriz
        for matriz in MatrizNaveRecurso.objects.filter(
            nave=periodo.nave,
            es_visible=True,
            recurso_id__in=recurso_ids,
            recurso__periodicidad_id=periodo.periodicidad_id,
        )
    }
    fichas_existentes = {
        ficha.recurso_id: ficha
        for ficha in FichaRegistro.objects.filter(
            periodo=periodo,
            recurso_id__in=recurso_ids,
        ).select_related("periodo", "recurso")
    }

    guardadas = 0
    errores = []

    for ficha_payload in fichas_payload:
        recurso_id = ficha_payload.get("recurso_id") if isinstance(ficha_payload, dict) else None
        try:
            data, mensaje_error = _validar_payload_ficha_dict(
                ficha_payload,
                require_recurso_id=True,
            )
            if mensaje_error:
                raise ValueError(mensaje_error)

            recurso_id = data["recurso_id"]
            recurso = recursos_por_id.get(recurso_id)
            if recurso is None:
                raise ValueError("Recurso no encontrado.")
            matriz = matrices_por_recurso_id.get(recurso_id)
            if matriz is None:
                raise ValueError("El recurso no está asignado a esta nave.")

            ficha_existente = fichas_existentes.get(recurso_id)

            estado_operativo = data["estado_operativo"]
            if estado_operativo is None:
                definicion = MotorFichas.obtener_definicion_checklist(
                    recurso, matriz.cantidad, ficha=ficha_existente
                )
                estado_operativo = MotorFichas.derivar_estado_operativo_desde_checklist(
                    definicion,
                    data["payload_checklist"],
                )

            if ficha_existente is not None:
                ficha = MotorFichas.modificar_ficha(
                    ficha=ficha_existente,
                    usuario_modificador=request.user,
                    estado_operativo=estado_operativo,
                    observacion_general=data["observacion_general"],
                    payload_checklist=data["payload_checklist"],
                )
            else:
                ficha = MotorFichas.crear_ficha(
                    periodo=periodo,
                    recurso=recurso,
                    usuario=request.user,
                    estado_operativo=estado_operativo,
                    observacion_general=data["observacion_general"],
                    payload_checklist=data["payload_checklist"],
                )

            fichas_existentes[recurso_id] = ficha
            guardadas += 1
        except ValueError as exc:
            logger.error(
                (
                    "api_guardar_fichas_periodo validation error "
                    "(periodo_id=%s, recurso_id=%s, user_id=%s)"
                ),
                periodo.id,
                recurso_id,
                getattr(request.user, "id", None),
                exc_info=True,
            )
            errores.append({"recurso_id": recurso_id, "error": str(exc)})
        except Exception:
            logger.error(
                (
                    "api_guardar_fichas_periodo unexpected error "
                    "(periodo_id=%s, recurso_id=%s, user_id=%s)"
                ),
                periodo.id,
                recurso_id,
                getattr(request.user, "id", None),
                exc_info=True,
            )
            errores.append(
                {
                    "recurso_id": recurso_id,
                    "error": "Error interno procesando la ficha.",
                }
            )

    return JsonResponse({"guardadas": guardadas, "errores": errores}, status=200)
