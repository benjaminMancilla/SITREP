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
    def buscar_dispositivo_por_token(naviera_id, token_plano):
        """Dispositivo (activo O revocado) cuyo token coincide, o None. El
        llamador decide qué hacer con is_active. Un solo lugar corre el loop
        de verificación — lo comparten el login de mar y el endpoint de
        verificación del frontend."""
        if not naviera_id or not token_plano:
            return None
        for d in Dispositivo.objects.filter(naviera_id=naviera_id).order_by("-is_active"):
            if d.verificar_token(token_plano):
                return d
        return None

    @staticmethod
    def get_tripulacion_de_nave(naviera, nave_id):
        nave = FleetQueryService.get_nave_activa(naviera, nave_id)
        return Tripulacion.objects.filter(nave=nave)

    @staticmethod
    def get_tripulacion_activa_de_nave(naviera, nave_id):
        nave = FleetQueryService.get_nave_activa(naviera, nave_id)
        return Tripulacion.objects.filter(nave=nave, usuario__is_active=True).select_related("usuario")

    @staticmethod
    def get_naves_capitan(user, naviera):
        return Nave.objects.filter(
            naviera=naviera, is_active=True, tripulantes__usuario=user
        ).distinct()

    @staticmethod
    def get_naves_scope(user, naviera):
        """None = sin restricción (ve todas las naves de la naviera)."""
        if user.rol == "capitan":
            return FleetQueryService.get_naves_capitan(user, naviera)
        return None

    @staticmethod
    def nave_en_scope(user, naviera, nave_id):
        scope = FleetQueryService.get_naves_scope(user, naviera)
        return scope is None or scope.filter(id=nave_id).exists()
