import logging

from django.conf import settings
from django.core.paginator import Paginator

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
    if secret and request.META.get("HTTP_X_CF_SECRET") == secret:
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
