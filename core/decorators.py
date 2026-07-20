from functools import wraps

from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import resolve_url

from core.permissions import ROLES_ADMIN, ROLES_ADMIN_CAPITAN, ROLES_KIOSCO, ROLES_TIERRA


def requiere_rol(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if getattr(request.user, "rol", None) not in roles:
                slug = kwargs.get("slug")
                login_url = resolve_url(f"/{slug}/login/") if slug else resolve_url("/admin/login/")
                logout(request)
                return redirect_to_login(request.get_full_path(), login_url=login_url)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def requiere_tierra(view_func):
    return requiere_rol(*ROLES_TIERRA)(view_func)


def requiere_kiosco(view_func):
    return requiere_rol(*ROLES_KIOSCO)(view_func)


def requiere_admin(view_func):
    return requiere_rol(*ROLES_ADMIN)(view_func)


def requiere_admin_capitan(view_func):
    return requiere_rol(*ROLES_ADMIN_CAPITAN)(view_func)
