ROLES_API_KIOSCO = {"mar", "capitan", "tierra", "admin_naviera", "admin_sitrep"}


def tiene_rol_api_kiosco(user):
    """Returns True if user's role grants access to kiosco API endpoints."""
    return getattr(user, "rol", None) in ROLES_API_KIOSCO
