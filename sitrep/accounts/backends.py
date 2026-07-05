from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from sitrep.fleet.models import Dispositivo, Tripulacion

Usuario = get_user_model()


class WebTenantBackend(ModelBackend):
    def authenticate(self, request, email=None, password=None, **kwargs):
        if not email or not password:
            return None
        try:
            usuario = Usuario.objects.get(email=email)
        except (Usuario.DoesNotExist, Usuario.MultipleObjectsReturned):
            return None

        if usuario.naviera != getattr(request, "naviera", None):
            return None
        if usuario.rol == 'mar':
            return None
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None


class KioscoTenantBackend(ModelBackend):
    def authenticate(self, request, rut=None, pin=None, naviera_id=None, dispositivo_token=None, **kwargs):
        naviera_id = getattr(getattr(request, "naviera", None), "id", None)

        if not rut or not pin or not naviera_id or not dispositivo_token:
            return None

        dispositivo_autenticado = None
        for dispositivo in Dispositivo.objects.filter(naviera_id=naviera_id).order_by("-is_active"):
            if dispositivo.verificar_token(dispositivo_token):
                if not dispositivo.is_active:
                    if request is not None:
                        request._dispositivo_revocado = True
                    return None
                dispositivo_autenticado = dispositivo
                break

        if not dispositivo_autenticado:
            return None

        try:
            usuario = Usuario.objects.get(rut=rut, naviera_id=naviera_id)
            if not usuario.check_pin(pin) or not self.user_can_authenticate(usuario):
                return None
            if not Tripulacion.objects.filter(usuario=usuario, nave_id=dispositivo_autenticado.nave_id).exists():
                return None
            usuario._dispositivo_autenticado = dispositivo_autenticado
            return usuario
        except (Usuario.DoesNotExist, Usuario.MultipleObjectsReturned):
            return None
