from functools import wraps

from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import resolve_url


def tenant_member_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            slug = kwargs.get("slug")
            login_url = resolve_url(f"/{slug}/login/") if slug else resolve_url("/admin/login/")
            return redirect_to_login(request.get_full_path(), login_url=login_url)

        if not getattr(request.user, "es_admin_sitrep_global", False) and \
                getattr(request.user, "naviera", None) != getattr(request, "naviera", None):
            slug = kwargs.get("slug")
            login_url = resolve_url(f"/{slug}/login/") if slug else resolve_url("/")
            return redirect_to_login(request.get_full_path(), login_url=login_url)

        return view_func(request, *args, **kwargs)

    return _wrapped


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
