from django.shortcuts import render

from core.decorators import requiere_rol
from core.permissions import ROLES_ADMIN_SITREP
from sitrep.accounts.decorators import tenant_member_required
from sitrep.fleet.services import FleetQueryService

from .models import Area, Periodicidad, Recurso


@tenant_member_required
@requiere_rol(*ROLES_ADMIN_SITREP)
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
