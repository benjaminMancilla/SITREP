from django.shortcuts import render

from sitrep.accounts.decorators import requiere_rol, tenant_member_required
from sitrep.fleet.services import FleetQueryService

from .models import Area, Periodicidad, Recurso


@tenant_member_required
@requiere_rol("admin_sitrep")
def catalogo_admin(request, slug):
    context = {
        "slug": slug,
        "naves": FleetQueryService.get_naves_activas(request.naviera),
        "categorias": Recurso.CATEGORIA_CHOICES,
        "tipos": Recurso.TIPO_CHOICES,
        "periodicidades": Periodicidad.objects.all(),
        "areas": Area.objects.all(),
    }
    return render(request, "catalog/catalogo_admin.html", context)
