from django.contrib.auth import get_user_model
from django.http import Http404

Usuario = get_user_model()


class AccountsQueryService:
    @staticmethod
    def _get_or_404(model, **kwargs):
        try:
            return model.objects.get(**kwargs)
        except model.DoesNotExist as exc:
            raise Http404("Recurso no encontrado.") from exc

    @staticmethod
    def get_usuario_del_tenant(naviera, usuario_id):
        return AccountsQueryService._get_or_404(Usuario, id=usuario_id, naviera=naviera)

    @staticmethod
    def get_usuario_activo_del_tenant(naviera, usuario_id):
        return AccountsQueryService._get_or_404(Usuario, id=usuario_id, naviera=naviera, is_active=True)

    @staticmethod
    def get_usuarios_del_tenant(naviera):
        return Usuario.objects.filter(naviera=naviera, is_active=True, is_superuser=False)
