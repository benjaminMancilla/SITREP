from rest_framework.views import APIView

from sitrep.fleet.services import FleetQueryService

from .permissions import EsKiosco, EsTierra


class TierraAPIView(APIView):
    """
    Base para endpoints del área tierra.
    Capitán -> scoped a sus naves. Otros roles -> todas las naves de la naviera.
    """
    permission_classes = [EsTierra]

    def get_naves_scope(self, request):
        if request.user.rol == "capitan":
            return FleetQueryService.get_naves_capitan(request.user, request.naviera)
        return None


class KioscoAPIView(APIView):
    """Base para endpoints del área kiosco."""
    permission_classes = [EsKiosco]
