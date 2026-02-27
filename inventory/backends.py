from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from .models import Dispositivo

Usuario = get_user_model()

class WebTenantBackend(ModelBackend):
    """
    VECTOR TIERRA: Autenticación administrativa y operativa remota.
    Se basa en el conocimiento (Email + Contraseña Fuerte).
    """
    def authenticate(self, request, email=None, password=None, **kwargs):
        if not email or not password:
            return None
            
        try:
            usuario = Usuario.objects.get(email=email)
            
            # EL ESCUDO DE ROLES: Un marinero raso tiene estrictamente prohibido entrar a la web
            if usuario.rol == 'mar':
                return None
                
            # Verificación del hash de la contraseña larga de Django
            if usuario.check_password(password) and self.user_can_authenticate(usuario):
                return usuario
                
        except Usuario.DoesNotExist:
            return None
            
        return None


class KioscoTenantBackend(ModelBackend):
    """
    VECTOR MAR: Autenticación operativa en terreno (Embarcaciones).
    Se basa en posesión (Tablet física) y conocimiento (RUT + PIN).
    """
    def authenticate(self, request, rut=None, pin=None, naviera_id=None, dispositivo_token=None, **kwargs):
        # Filtro de Integridad de la Petición
        if not rut or not pin or not naviera_id:
            return None
            
        # ESCUDO DE HARDWARE BINDING
        # Si la petición no adjunta el token inyectado en la tablet, se rechaza de inmediato.
        if not dispositivo_token:
            return None

        dispositivos_activos = Dispositivo.objects.filter(naviera_id=naviera_id, is_active=True)
        
        dispositivo_valido = False
        for dispositivo in dispositivos_activos:
            if dispositivo.verificar_token(dispositivo_token):
                dispositivo_valido = True
                break
                
        if not dispositivo_valido:
            return None

        # VERIFICACIÓN DE IDENTIDAD Y SECRETO
        try:
            # Buscamos al usuario en su tenant específico
            usuario = Usuario.objects.get(rut=rut, naviera_id=naviera_id)
            
            # Verificamos que el PIN ingresado coincida con el hash
            if usuario.check_pin(pin) and self.user_can_authenticate(usuario):
                return usuario
                
        except Usuario.DoesNotExist:
            return None
            
        return None