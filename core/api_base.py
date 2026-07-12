from rest_framework.views import APIView

from sitrep.fleet.services import FleetQueryService

from core.security_alerts import report_security_incident
from core.throttling import ApiRateThrottle

from .permissions import EsKiosco, EsTierra


class _AuditingAPIView(APIView):
    """
    Deja un AuditEvent por cada respuesta exitosa de un endpoint marcado con
    audit_resource. Opt-in (no todo endpoint toca PII) para no llenar la
    tabla ni gastar un INSERT donde no aporta.

    También aplica ApiRateThrottle a todo endpoint que herede de esta clase
    (heredado, nunca instanciado a mano) y reporta cualquier bloqueo a
    Sentry + AuditEvent antes de que DRF devuelva el 429.
    """

    audit_resource = None  # ej. "usuarios" — si se define, se audita
    audit_accion = "read"
    throttle_classes = [ApiRateThrottle]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if self.audit_resource and response.status_code < 400 and getattr(request.user, "is_authenticated", False):
            from sitrep.accounts.audit import registrar_acceso

            detalle = ""
            data = getattr(response, "data", None)
            if isinstance(data, list):
                detalle = f"count={len(data)}"
            elif isinstance(data, dict) and isinstance(data.get("results"), list):
                detalle = f"count={len(data['results'])}"
            elif isinstance(data, dict) and "id" in data:
                detalle = f"id={data['id']}"

            registrar_acceso(request, self.audit_accion, self.audit_resource, detalle)
        return response

    def throttled(self, request, wait):
        report_security_incident(
            "rate_limit_exceeded", request=request, level="warning",
            wait_seconds=wait, method=request.method,
        )
        if getattr(request.user, "is_authenticated", False):
            from sitrep.accounts.audit import registrar_acceso

            registrar_acceso(
                request, "blocked", "throttle",
                detalle=f"method={request.method} wait={wait}s",
            )
        super().throttled(request, wait)


class TierraAPIView(_AuditingAPIView):
    """
    Base para endpoints del área tierra.
    Capitán -> scoped a sus naves. Otros roles -> todas las naves de la naviera.
    """
    permission_classes = [EsTierra]

    def get_naves_scope(self, request):
        if request.user.rol == "capitan":
            return FleetQueryService.get_naves_capitan(request.user, request.naviera)
        return None


class KioscoAPIView(_AuditingAPIView):
    """Base para endpoints del área kiosco."""
    permission_classes = [EsKiosco]
