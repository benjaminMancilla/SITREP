from django.shortcuts import render

from sitrep.accounts.decorators import requiere_rol, tenant_member_required
from sitrep.fleet.services import FleetQueryService

from .models import Area, Periodicidad, Proposito


@tenant_member_required
@requiere_rol("admin_sitrep")
def catalogo_admin(request, slug):
    context = {
        "slug": slug,
        "naves": FleetQueryService.get_naves_activas(request.naviera),
        "propositos": Proposito.objects.all(),
        "periodicidades": Periodicidad.objects.all(),
        "areas": Area.objects.all(),
    }
    return render(request, "catalog/catalogo_admin.html", context)
