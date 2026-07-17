import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import HttpResponse

logger = logging.getLogger(__name__)
_warned_no_secret = False


def paginate(queryset, page, per_page):
    return Paginator(queryset, per_page).get_page(page)


def get_client_ip(request):
    """
    IP real del cliente detrás de Cloudflare.

    Solo confía en CF-Connecting-IP si viene acompañada del header secreto
    que agrega una Cloudflare Transform Rule (settings.CLOUDFLARE_SHARED_SECRET).
    Sin eso, cualquiera que le pegue directo a la app (ej. el dominio *.railway.app)
    podría falsificar CF-Connecting-IP. Si no hay secreto configurado, se usa
    REMOTE_ADDR (la IP del proxy inmediato) y se loguea una única advertencia.
    """
    global _warned_no_secret
    secret = getattr(settings, "CLOUDFLARE_SHARED_SECRET", "")
    if secret and request.META.get("HTTP_X_ORIGIN_SECRET") == secret:
        cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
        if cf_ip:
            return cf_ip
    elif not secret and not _warned_no_secret:
        _warned_no_secret = True
        logger.warning(
            "CLOUDFLARE_SHARED_SECRET no configurado: get_client_ip() usa REMOTE_ADDR, "
            "que puede no ser la IP real si hay proxies delante."
        )
    return request.META.get("REMOTE_ADDR")


def hit_rate_limit(key_prefix, request, limit, window_seconds):
    """True si esta IP ya superó `limit` requests en la ventana. Ventana fija
    sobre el cache de Django. Sirve tanto para el decorador `throttle` como para
    limitar una rama puntual de una vista (ej. solo el POST de mar en el login).
    """
    cache_key = f"throttle:{key_prefix}:{get_client_ip(request)}"
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, window_seconds)
        count = 1
    return count > limit


def throttle(key_prefix, limit, window_seconds):
    """Máx `limit` requests cada `window_seconds` por IP a la vista decorada."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if hit_rate_limit(key_prefix, request, limit, window_seconds):
                return HttpResponse("Demasiadas solicitudes, intenta más tarde.", status=429)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def verify_turnstile(token, remote_ip):
    """Valida un token de Cloudflare Turnstile contra siteverify. False si falta, es inválido o falla la red."""
    if not token:
        return False
    data = urllib.parse.urlencode({
        "secret": settings.TURNSTILE_SECRET_KEY,
        "response": token,
        "remoteip": remote_ip,
    }).encode()
    try:
        with urllib.request.urlopen(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify", data=data, timeout=5
        ) as resp:
            result = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError):
        logger.exception("Fallo al verificar Turnstile")
        return False
    return bool(result.get("success"))
