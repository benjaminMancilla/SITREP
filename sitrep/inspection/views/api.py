import json
import logging

from django.db.models import Count
from django.http import Http404, JsonResponse

from sitrep.accounts.decorators import requiere_rol, tenant_member_required
from sitrep.catalog.models import Recurso

from ..models import FichaRegistro, MatrizNaveRecurso
from .. import repositories
from ..permissions import tiene_rol_api_kiosco
from ..services import TenantQueryService, MotorFichas, contar_fichas_completas_por_periodo

logger = logging.getLogger(__name__)


def _json_error(mensaje, status):
    return JsonResponse({"error": mensaje}, status=status)


def _validar_rol_api_kiosco(request):
    if not tiene_rol_api_kiosco(request.user):
        return _json_error("Acceso denegado: rango insuficiente.", 403)
    return None


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


def _extraer_payload_ficha_desde_json(request):
    payload, error = _cargar_payload_json(request)
    if error:
        return None, error

    data, mensaje_error = _validar_payload_ficha_dict(payload)
    if mensaje_error:
        return None, _json_error(mensaje_error, 400)

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
def api_periodos_nave(request, slug):
    if request.method != "GET":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodos = list(TenantQueryService.get_periodos_abiertos_de_nave(nave).order_by("fecha_inicio", "id"))
    periodicidad_ids = [periodo.periodicidad_id for periodo in periodos]
    periodo_ids = [periodo.id for periodo in periodos]

    recursos_por_periodicidad = {}
    if periodicidad_ids:
        recursos_por_periodicidad = {
            row["recurso__periodicidad_id"]: row["total"]
            for row in (
                MatrizNaveRecurso.objects.filter(
                    nave=nave,
                    es_visible=True,
                    recurso__periodicidad_id__in=periodicidad_ids,
                )
                .values("recurso__periodicidad_id")
                .annotate(total=Count("id"))
            )
        }

    fichas_por_periodo = contar_fichas_completas_por_periodo(periodo_ids)

    payload = {
        "nave": {
            "id": nave.id,
            "nombre": nave.nombre,
            "matricula": nave.matricula,
        },
        "periodos": [
            {
                "id": periodo.id,
                "periodicidad": periodo.periodicidad.nombre,
                "fecha_inicio": periodo.fecha_inicio.isoformat(),
                "fecha_termino": periodo.fecha_termino.isoformat(),
                "estado": periodo.get_estado_display(),
                "total_recursos": recursos_por_periodicidad.get(periodo.periodicidad_id, 0),
                "fichas_completadas": fichas_por_periodo.get(periodo.id, 0),
            }
            for periodo in periodos
        ],
    }
    return JsonResponse(payload, status=200)


@tenant_member_required
def api_recursos_periodo(request, slug, periodo_id):
    if request.method != "GET":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = repositories.get_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    recursos = []
    matrices = TenantQueryService.get_recursos_visibles_de_nave_en_periodo(nave, periodo).order_by(
        "recurso__nombre",
        "id",
    )
    for matriz in matrices:
        ficha = TenantQueryService.get_ficha_de_periodo_y_recurso(periodo, matriz.recurso)
        recursos.append(
            {
                "matriz_id": matriz.id,
                "recurso_id": matriz.recurso_id,
                "nombre": matriz.recurso.nombre,
                "tipo": matriz.recurso.proposito.tipo,
                "categoria": matriz.recurso.proposito.categoria,
                "cantidad": matriz.cantidad,
                "requerimientos": matriz.recurso.requerimientos or [],
                "checklist_items": MotorFichas.construir_checklist_items(
                    MotorFichas.obtener_definicion_checklist(matriz.recurso, matriz.cantidad, ficha=ficha),
                    ficha.payload_checklist if ficha else {},
                ),
                "tiene_ficha": ficha is not None,
                "estado_operativo": ficha.estado_operativo if ficha else None,
                "observacion_general": ficha.observacion_general if ficha else "",
            }
        )

    payload = {
        "periodo": {
            "id": periodo.id,
            "periodicidad": periodo.periodicidad.nombre,
            "fecha_inicio": periodo.fecha_inicio.isoformat(),
            "fecha_termino": periodo.fecha_termino.isoformat(),
        },
        "recursos": recursos,
    }
    return JsonResponse(payload, status=200)


@tenant_member_required
def api_detalle_recurso(request, slug, periodo_id, recurso_id):
    if request.method != "GET":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = repositories.get_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    try:
        matriz = MatrizNaveRecurso.objects.select_related(
            "recurso",
            "recurso__proposito",
            "recurso__periodicidad",
        ).get(
            nave=nave,
            recurso_id=recurso_id,
            es_visible=True,
            recurso__periodicidad_id=periodo.periodicidad_id,
        )
    except MatrizNaveRecurso.DoesNotExist:
        return _json_error("Recurso no encontrado en la matriz visible de la nave.", 404)

    ficha = TenantQueryService.get_ficha_de_periodo_y_recurso(periodo, matriz.recurso)
    usuario_ficha = None
    estado_operativo = None
    observacion_general = ""
    payload_checklist = {}
    fecha_revision = None

    if ficha:
        estado_operativo = ficha.estado_operativo
        observacion_general = ficha.observacion_general
        payload_checklist = MotorFichas.normalizar_payload_checklist(ficha.payload_checklist or {})
        fecha_revision = ficha.fecha_revision.isoformat() if ficha.fecha_revision else None

        nombre_completo = f"{ficha.usuario.first_name} {ficha.usuario.last_name}".strip()
        if not nombre_completo:
            nombre_completo = ficha.usuario.rut
        usuario_ficha = f"{nombre_completo} ({ficha.usuario.rut})"

    payload = {
        "recurso": {
            "id": matriz.recurso.id,
            "nombre": matriz.recurso.nombre,
            "tipo": matriz.recurso.proposito.tipo,
            "categoria": matriz.recurso.proposito.categoria,
            "cantidad_requerida": matriz.cantidad,
            "requerimientos": matriz.recurso.requerimientos or [],
            "checklist_items": MotorFichas.construir_checklist_items(
                MotorFichas.obtener_definicion_checklist(matriz.recurso, matriz.cantidad, ficha=ficha),
                payload_checklist,
            ),
        },
        "ficha": {
            "existe": ficha is not None,
            "estado_operativo": estado_operativo,
            "observacion_general": observacion_general,
            "payload_checklist": payload_checklist,
            "fecha_revision": fecha_revision,
            "usuario": usuario_ficha,
        },
    }
    return JsonResponse(payload, status=200)


@tenant_member_required
def api_crear_ficha(request, slug, periodo_id, recurso_id):
    if request.method != "POST":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = repositories.get_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    try:
        recurso = Recurso.objects.get(id=recurso_id)
    except Recurso.DoesNotExist:
        return _json_error("Recurso no encontrado.", 404)

    data, error = _extraer_payload_ficha_desde_json(request)
    if error:
        return error

    try:
        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=request.user,
            estado_operativo=data["estado_operativo"],
            observacion_general=data["observacion_general"],
            payload_checklist=data["payload_checklist"],
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    return JsonResponse({"id": ficha.id, "created": True}, status=201)


@tenant_member_required
def api_modificar_ficha(request, slug, periodo_id, recurso_id):
    if request.method != "PATCH":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = repositories.get_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    try:
        ficha = FichaRegistro.objects.get(periodo=periodo, recurso_id=recurso_id)
    except FichaRegistro.DoesNotExist:
        return _json_error("Ficha no encontrada para este recurso y período.", 404)

    data, error = _extraer_payload_ficha_desde_json(request)
    if error:
        return error

    try:
        ficha = MotorFichas.modificar_ficha(
            ficha=ficha,
            usuario_modificador=request.user,
            estado_operativo=data["estado_operativo"],
            observacion_general=data["observacion_general"],
            payload_checklist=data["payload_checklist"],
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    return JsonResponse({"id": ficha.id, "modified": True}, status=200)


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
