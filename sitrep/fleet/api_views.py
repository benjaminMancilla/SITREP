from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.throttling import AnonIPRateThrottle
from core.utils import get_client_ip
from sitrep.accounts.models import AuditEvent
from sitrep.fleet.services import FleetQueryService


class VerificarDispositivoView(APIView):
    """Dice si el token de kiosco que trae el cliente sigue vigente (dispositivo
    existe, es de esta naviera y is_active=True). Lo consume el login para no
    confiar solo en la presencia del token en localStorage. Anónimo: se llama
    antes de autenticar. Throttle por IP porque corre el mismo loop de
    check_password por dispositivo que el login — superficie de DoS si no se
    limita."""

    authentication_classes = []  # anónimo; además hace que DRF omita CSRF
    permission_classes = [AllowAny]
    throttle_classes = [AnonIPRateThrottle]

    def post(self, request, slug):
        token = request.data.get("token")
        naviera = getattr(request, "naviera", None)
        dispositivo = FleetQueryService.buscar_dispositivo_por_token(
            getattr(naviera, "id", None), token
        )
        valido = bool(dispositivo and dispositivo.is_active)
        if token and not valido:  # token viejo/revocado/inválido presentado: señal de auditoría
            AuditEvent.objects.create(
                naviera=naviera,
                accion="blocked",
                recurso="dispositivo_token",
                ip=get_client_ip(request),
                endpoint=request.path,
            )
        return Response({"valido": valido})
