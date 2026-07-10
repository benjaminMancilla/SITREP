from django.http import Http404

from .models import Naviera


class TenantMiddleware:
    GLOBAL_PREFIXES = {"admin", "static", "media", "health", "legal", "contacto", "arco"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info or "/"
        parts = [s for s in path.split("/") if s]

        if not parts or parts[0] in self.GLOBAL_PREFIXES:
            return self.get_response(request)

        first_segment = parts[0]
        if not path.startswith(f"/{first_segment}/"):
            return self.get_response(request)

        try:
            request.naviera = Naviera.objects.get(slug=first_segment)
        except Naviera.DoesNotExist as exc:
            raise Http404("Naviera no encontrada.") from exc

        return self.get_response(request)
