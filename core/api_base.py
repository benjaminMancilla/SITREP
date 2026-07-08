from rest_framework.views import APIView

from sitrep.fleet.services import FleetQueryService

from .permissions import EsKiosco, EsTierra


class _AuditingAPIView(APIView):
    """
    Deja un AuditEvent por cada respuesta exitosa de un endpoint marcado con
    audit_resource. Opt-in (no todo endpoint toca PII) para no llenar la
    tabla ni gastar un INSERT donde no aporta.
    """

    audit_resource = None  # ej. "usuarios" — si se define, se audita
    audit_accion = "read"

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
