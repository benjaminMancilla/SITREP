from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from core.utils import get_client_ip

READ_RATE = "120/min"
WRITE_RATE = "30/min"
_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class ApiRateThrottle(UserRateThrottle):
    """Límite por usuario para todo endpoint DRF del proyecto. Un solo
    mecanismo: el rate varía según el método HTTP, nunca una segunda clase
    de throttle para escritura. Se usa heredando throttle_classes en una
    vista base — nunca instanciar ni llamar a mano.

    Lectura y escritura usan cache keys distintas (self.scope cambia según
    el método) para que sean presupuestos realmente independientes: DRF
    arma la cache key solo a partir de self.scope + usuario
    (get_cache_key), no del rate — con un solo scope fijo, agotar el cupo
    de lecturas también bloquearía la primera escritura del usuario."""

    scope = "api_read"
    # ponytail: DRF exige una entrada en THROTTLE_RATES para self.scope al
    # instanciar (antes de que corra allow_request); se define acá en vez
    # de settings.py porque el rate real lo decide allow_request() por
    # request, no una config estática de DRF.
    THROTTLE_RATES = {"api_read": READ_RATE, "api_write": WRITE_RATE}

    def allow_request(self, request, view):
        if request.method in _SAFE_METHODS:
            self.scope = "api_read"
            self.rate = READ_RATE
        else:
            self.scope = "api_write"
            self.rate = WRITE_RATE
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)


class AnonIPRateThrottle(AnonRateThrottle):
    """Límite por IP para endpoints DRF anónimos (sin usuario). ApiRateThrottle
    es por usuario y no sirve acá; y un APIView crudo que no herede de
    TierraAPIView/KioscoAPIView no queda limitado por defecto. Usa el IP
    Cloudflare-aware del proyecto en vez del REMOTE_ADDR crudo de DRF."""

    scope = "anon_ip"
    THROTTLE_RATES = {"anon_ip": "20/min"}

    def get_ident(self, request):
        return get_client_ip(request)
