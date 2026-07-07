from rest_framework.response import Response

from core.api_base import TierraAPIView
from sitrep.fleet.models import Nave

from .presenters import construir_tabla_urgencia


class UrgenciaPorPeriodicidadView(TierraAPIView):
    def get(self, request, slug):
        naves = self._resolver_naves(request)
        if isinstance(naves, Response):
            return naves
        data = construir_tabla_urgencia(request.naviera, naves=naves)
        return Response(data)

    def _resolver_naves(self, request):
        base = self.get_naves_scope(request)
        param = request.query_params.get("naves", "").strip()
        if not param:
            return base
        try:
            ids = [int(i) for i in param.split(",") if i.strip()]
        except ValueError:
            return Response({"error": "Parámetro 'naves' inválido"}, status=400)
        if base is not None:
            return base.filter(id__in=ids)
        return Nave.objects.filter(id__in=ids)
