from django.contrib import admin
from django.db.models import F
from django.http import HttpResponseForbidden
from django.template.response import TemplateResponse
from django.urls import path
import json

from sitrep.accounts.models import Naviera
from .models import Area, Periodicidad, Proposito, Recurso


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ["orden", "nombre", "nombre_tecnico", "token_color"]
    list_editable = ["orden"]
    list_display_links = ["nombre"]
    ordering = [F("orden").asc(nulls_last=True)]
    search_fields = ["nombre", "nombre_tecnico"]
    list_filter = ["token_color"]


@admin.register(Recurso)
class RecursoAdmin(admin.ModelAdmin):
    list_display = (
        "codigo", "nombre", "naviera", "area", "proposito",
        "periodicidad", "created_at", "tiene_regla", "num_requerimientos",
    )
    list_filter = ("naviera", "proposito", "periodicidad", "area")
    search_fields = ("codigo", "nombre")
    readonly_fields = ("created_at",)

    def tiene_regla(self, obj):
        return bool(obj.regla_aplicacion)
    tiene_regla.boolean = True
    tiene_regla.short_description = "Tiene Regla"

    def num_requerimientos(self, obj):
        return len(obj.requerimientos) if obj.requerimientos else 0
    num_requerimientos.short_description = "# Requerimientos"


class ImportarRecursosAdmin(admin.ModelAdmin):
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "importar-json/",
                self.admin_site.admin_view(self.importar_view),
                name="inventory_importar_recursos",
            ),
        ]
        return custom + urls

    def importar_view(self, request):
        from sitrep.inventory.management.commands.load_recursos import ejecutar_carga

        if not request.user.is_superuser:
            return HttpResponseForbidden("Solo superusuarios pueden importar recursos.")

        context = {
            **self.admin_site.each_context(request),
            "title": "Importar recursos desde JSON",
            "navieras": Naviera.objects.all().order_by("nombre"),
            "resultado": None,
            "opts": self.model._meta,
        }

        if request.method == "POST":
            archivo = request.FILES.get("json_file")
            scope = request.POST.get("scope", "global")
            naviera_id = request.POST.get("naviera_id", "")
            dry_run = request.POST.get("dry_run") == "on"

            if not archivo:
                context["error"] = "Debes seleccionar un archivo JSON."
                return TemplateResponse(request, "admin/inventory/importar_recursos.html", context)

            try:
                contenido = archivo.read().decode("utf-8")
                json_data = json.loads(contenido)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                context["error"] = f"Archivo inválido: {e}"
                return TemplateResponse(request, "admin/inventory/importar_recursos.html", context)

            naviera = None
            if scope == "naviera" and naviera_id:
                try:
                    naviera = Naviera.objects.get(pk=naviera_id)
                except Naviera.DoesNotExist:
                    context["error"] = "Naviera no encontrada."
                    return TemplateResponse(request, "admin/inventory/importar_recursos.html", context)

            stats = ejecutar_carga(json_data, naviera=naviera, dry_run=dry_run)
            context["resultado"] = stats
            context["dry_run"] = dry_run

        return TemplateResponse(request, "admin/inventory/importar_recursos.html", context)

    def has_module_perms(self, user):
        return user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["importar_url"] = "/admin/catalog/proposito/importar-json/"
        return super().changelist_view(request, extra_context=extra_context)


admin.site.register(Proposito, ImportarRecursosAdmin)
admin.site.register(Periodicidad)
