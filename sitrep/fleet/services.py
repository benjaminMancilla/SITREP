from django.http import Http404

from sitrep.fleet.models import Dispositivo, Nave, Tripulacion


class FleetQueryService:
    @staticmethod
    def _get_or_404(model, **kwargs):
        try:
            return model.objects.get(**kwargs)
        except model.DoesNotExist as exc:
            raise Http404("Recurso no encontrado.") from exc

    @staticmethod
    def get_nave(naviera, nave_id):
        return FleetQueryService._get_or_404(Nave, id=nave_id, naviera=naviera)

    @staticmethod
    def get_nave_activa(naviera, nave_id):
        return FleetQueryService._get_or_404(Nave, id=nave_id, naviera=naviera, is_active=True)

    @staticmethod
    def get_naves_activas(naviera):
        return Nave.objects.filter(naviera=naviera, is_active=True)

    @staticmethod
    def get_naves_del_tenant(naviera):
        return Nave.objects.filter(naviera=naviera).order_by("is_active", "nombre")

    @staticmethod
    def get_dispositivo(naviera, dispositivo_id):
        return FleetQueryService._get_or_404(Dispositivo, id=dispositivo_id, naviera=naviera)

    @staticmethod
    def get_dispositivos(naviera):
        return Dispositivo.objects.filter(naviera=naviera).select_related("nave")

    @staticmethod
    def get_tripulacion_de_nave(naviera, nave_id):
        nave = FleetQueryService.get_nave_activa(naviera, nave_id)
        return Tripulacion.objects.filter(nave=nave)

    @staticmethod
    def get_tripulacion_activa_de_nave(naviera, nave_id):
        nave = FleetQueryService.get_nave_activa(naviera, nave_id)
        return Tripulacion.objects.filter(nave=nave, usuario__is_active=True).select_related("usuario")
