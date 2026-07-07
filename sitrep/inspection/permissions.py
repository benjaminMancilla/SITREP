from core.permissions import ROLES_KIOSCO


def tiene_rol_api_kiosco(user):
    """Returns True if user's role grants access to kiosco API endpoints."""
    return getattr(user, "rol", None) in ROLES_KIOSCO
