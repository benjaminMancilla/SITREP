from rest_framework.throttling import UserRateThrottle

READ_RATE = "120/min"
WRITE_RATE = "30/min"
_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class ApiRateThrottle(UserRateThrottle):
    """Límite por usuario para todo endpoint DRF del proyecto. Un solo
    mecanismo: el rate varía según el método HTTP, nunca una segunda clase
    de throttle para escritura. Se usa heredando throttle_classes en una
    vista base — nunca instanciar ni llamar a mano."""

    scope = "api"
    THROTTLE_RATES = {"api": READ_RATE}  # ponytail: default, overridden per-request in allow_request

    def allow_request(self, request, view):
        self.rate = READ_RATE if request.method in _SAFE_METHODS else WRITE_RATE
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)
