from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import resolve_url
from django.contrib.auth.views import redirect_to_login


def tenant_member_required(view_func):
    """
    Exige sesión autenticada y pertenencia del usuario al tenant resuelto.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            slug = kwargs.get("slug")
            login_url = resolve_url(f"/{slug}/login/") if slug else resolve_url("/admin/login/")
            return redirect_to_login(request.get_full_path(), login_url=login_url)

        if getattr(request.user, "naviera", None) != getattr(request, "naviera", None):
            slug = kwargs.get("slug")
            login_url = resolve_url(f"/{slug}/login/") if slug else resolve_url("/")
            return redirect_to_login(request.get_full_path(), login_url=login_url)

        return view_func(request, *args, **kwargs)

    return _wrapped


def requiere_rol(*roles):
    """
    Exige que el usuario autenticado tenga uno de los roles permitidos.
    Debe aplicarse después de @tenant_member_required.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if getattr(request.user, "rol", None) not in roles:
                return HttpResponseForbidden("Acceso denegado: rango insuficiente.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
