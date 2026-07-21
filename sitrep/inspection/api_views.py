from rest_framework.response import Response

from core.api_base import TierraAPIView
from sitrep.fleet.models import Nave

from .presenters import (
    construir_eventos_fallo_resolucion,
    construir_hitos_inminentes,
    construir_tabla_urgencia,
)


class FallosFeedView(TierraAPIView):
    def get(self, request, slug):
        naves = self.get_naves_scope(request)
        dias = self._resolver_dias(request)
        if isinstance(dias, Response):
            return dias
        eventos = construir_eventos_fallo_resolucion(request.naviera, naves=naves, dias=dias)
        return Response(eventos)

    def _resolver_dias(self, request):
        param = request.query_params.get("dias", "").strip()
        if not param:
            return None
        try:
            dias = int(param)
        except ValueError:
            return Response({"error": "Parámetro 'dias' inválido"}, status=400)
        if dias <= 0:
            return Response({"error": "Parámetro 'dias' inválido"}, status=400)
        return dias


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


class HitosInminentesView(TierraAPIView):
    def get(self, request, slug):
        naves = self.get_naves_scope(request)
        hitos = construir_hitos_inminentes(request.naviera, naves=naves)
        return Response(hitos)
