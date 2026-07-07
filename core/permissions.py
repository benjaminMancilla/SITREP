from rest_framework.permissions import BasePermission

ROLES_TIERRA = {"admin_sitrep", "admin_naviera", "capitan", "tierra"}
ROLES_KIOSCO = {"mar", "capitan", "tierra", "admin_naviera", "admin_sitrep"}


class EsTierra(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, "rol", None) in ROLES_TIERRA


class EsKiosco(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, "rol", None) in ROLES_KIOSCO
