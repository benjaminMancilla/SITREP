from datetime import timedelta

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api_base import TierraAPIView
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


class NavesEstadoView(TierraAPIView):
    def get(self, request, slug):
        naves = FleetQueryService.get_naves_con_estado(request.naviera)
        naves_scope = self.get_naves_scope(request)
        if naves_scope is not None:
            naves = naves.filter(id__in=naves_scope)
        data = [
            {
                "id": nave.id,
                "nombre": nave.nombre,
                "matricula": nave.matricula,
                "eslora": float(nave.eslora),
                "arqueoBruto": nave.arqueo_bruto,
                "capacidadPersonas": nave.capacidad_personas,
                "periodosAbiertos": nave.periodos_abiertos,
                "fallosActivos": nave.fallos_activos,
                "fallosNuevos": nave.fallos_nuevos,
                "resoluciones": nave.resoluciones,
                "fichasHoy": nave.fichas_hoy,
                "ultimaFichaEn": nave.ultima_ficha_en,
            }
            for nave in naves.order_by("nombre")
        ]
        return Response(data)


class FleetActividadView(TierraAPIView):
    """`?semanas=N` deja que cada vista (dashboard, naves) pida su propia
    ventana desde el mismo endpoint — el costo sigue acotado porque `dias`
    solo cambia el filtro de fecha de la query GROUP BY."""

    DEFAULT_SEMANAS = 6
    MAX_SEMANAS = 52

    def _parse_semanas(self, request):
        raw = request.query_params.get("semanas")
        try:
            semanas = int(raw) if raw is not None else self.DEFAULT_SEMANAS
        except ValueError:
            semanas = self.DEFAULT_SEMANAS
        return max(1, min(semanas, self.MAX_SEMANAS))

    def get(self, request, slug):
        dias = self._parse_semanas(request) * 7
        naves = FleetQueryService.get_naves_activas(request.naviera)
        naves_scope = self.get_naves_scope(request)
        if naves_scope is not None:
            naves = naves.filter(id__in=naves_scope)
        naves = list(naves.order_by("nombre"))

        inicio, conteos = FleetQueryService.get_actividad_diaria(
            request.naviera, nave_ids=[n.id for n in naves], dias=dias
        )
        data = []
        for nave in naves:
            por_dia = conteos.get(nave.id, {})
            dias_nave = [
                {
                    "date": (inicio + timedelta(days=i)).isoformat(),
                    "count": por_dia.get(inicio + timedelta(days=i), 0),
                }
                for i in range(dias)
            ]
            data.append({"id": nave.id, "nombre": nave.nombre, "matricula": nave.matricula, "days": dias_nave})
        return Response(data)
