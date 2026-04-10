from django.http import Http404

from .models import Naviera


class TenantMiddleware:
    """
    Resuelve el tenant por slug en rutas con prefijo /<slug>/.
    Rutas globales como /admin/ se ignoran.
    """

    GLOBAL_PREFIXES = {"admin", "static", "media"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info or "/"
        parts = [segment for segment in path.split("/") if segment]

        # Sin primer segmento, no hay slug que resolver.
        if not parts:
            return self.get_response(request)

        first_segment = parts[0]

        # Rutas globales que no pertenecen a tenants.
        if first_segment in self.GLOBAL_PREFIXES:
            return self.get_response(request)

        # Solo procesa paths con formato /<slug>/...
        if not path.startswith(f"/{first_segment}/"):
            return self.get_response(request)

        try:
            request.naviera = Naviera.objects.get(slug=first_segment)
        except Naviera.DoesNotExist as exc:
            raise Http404("Naviera no encontrada.") from exc

        return self.get_response(request)
