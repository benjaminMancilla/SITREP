from rest_framework.permissions import BasePermission

ROLES_TIERRA = {"admin_sitrep", "admin_naviera", "capitan", "tierra"}
ROLES_KIOSCO = {"mar", "capitan", "tierra", "admin_naviera", "admin_sitrep"}


class EsTierra(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, "rol", None) in ROLES_TIERRA


class EsKiosco(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, "rol", None) in ROLES_KIOSCO


class PuedeEditarCatalogo(BasePermission):
    """
    Quién puede escribir en el catálogo dinámico. Hoy: solo admin_sitrep, en
    cualquier scope (central o en nombre de cualquier naviera/nave). Cuando
    exista el rol asesor (global o por naviera, posiblemente combinado con
    otro rol), este es el único lugar a cambiar.
    """
    def has_permission(self, request, view):
        return getattr(request.user, "rol", None) == "admin_sitrep"
