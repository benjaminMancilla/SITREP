import logging
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


def throttle(key_prefix, limit, window_seconds):
    """Máx `limit` requests cada `window_seconds` por IP a la vista decorada.

    Usa el cache de Django (ventana fija, no distribuida entre procesos si el
    backend es LocMemCache — suficiente para frenar abuso de un endpoint
    público de bajo tráfico; cambiar a un cache compartido si hace falta
    consistencia entre workers).
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            cache_key = f"throttle:{key_prefix}:{get_client_ip(request)}"
            try:
                count = cache.incr(cache_key)
            except ValueError:
                cache.set(cache_key, 1, window_seconds)
                count = 1
            if count > limit:
                return HttpResponse("Demasiadas solicitudes, intenta más tarde.", status=429)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
