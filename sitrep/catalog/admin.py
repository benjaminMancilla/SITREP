from django.contrib import admin
from django.db.models import F
from django.http import HttpResponseForbidden
from django.template.response import TemplateResponse
from django.urls import path
import json

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
        "codigo", "nombre", "area", "proposito", "periodicidad",
        "naviera", "nave", "catalogo_version", "activo",
        "created_at", "tiene_regla", "num_requerimientos",
    )
    list_filter = ("proposito", "periodicidad", "area", "activo", "naviera")
    search_fields = ("codigo", "nombre")
    readonly_fields = (
        "nombre", "codigo", "area", "proposito", "periodicidad", "descripcion", "created_at",
        "naviera", "nave", "catalogo_version", "linaje_raiz", "activo",
        "requerimientos", "regla_aplicacion", "resumen_requerimientos_especiales",
    )
    fieldsets = (
        (None, {"fields": ("nombre", "codigo", "area", "proposito", "periodicidad", "descripcion", "created_at")}),
        ("Versionado", {"fields": ("naviera", "nave", "catalogo_version", "linaje_raiz", "activo")}),
        ("Requerimientos especiales", {
            "description": (
                "Cantidad y condición son requerimientos tipados dentro de "
                "'Requerimientos' (tipo: \"cantidad\" / \"condicion\"). El texto y el "
                "número de \"cantidad\", y la visibilidad del recurso, salen de 'Regla "
                "de aplicación' — no se escriben a mano."
            ),
            "fields": ("requerimientos", "regla_aplicacion", "resumen_requerimientos_especiales"),
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def tiene_regla(self, obj):
        return bool(obj.regla_aplicacion)
    tiene_regla.boolean = True
    tiene_regla.short_description = "Tiene Regla"

    def num_requerimientos(self, obj):
        return len(obj.requerimientos) if obj.requerimientos else 0
    num_requerimientos.short_description = "# Requerimientos"

    def resumen_requerimientos_especiales(self, obj):
        reqs = [r for r in (obj.requerimientos or []) if isinstance(r, dict)]
        tiene_cantidad = any(r.get("tipo") == "cantidad" for r in reqs)
        condiciones = [r.get("id") for r in reqs if r.get("tipo") == "condicion"]

        partes = [f"cantidad: {'sí' if tiene_cantidad else 'no'}"]
        partes.append(f"condición: {len(condiciones)}" + (f" ({', '.join(condiciones)})" if condiciones else ""))

        regla = obj.regla_aplicacion
        if regla:
            partes.append(
                f"regla: v{regla.get('version', 1)}, atributo={regla.get('atributo')!r}, "
                f"{len(regla.get('condiciones', []))} condición(es) de regla, "
                f"fallback cantidad={regla.get('fallback_cantidad')} "
                f"visible={regla.get('fallback_visible')}"
            )
        else:
            partes.append("regla: ninguna (cantidad=0, es_visible=True siempre)")

        return " · ".join(partes)
    resumen_requerimientos_especiales.short_description = "Resumen (calculado, no editable)"


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
        from sitrep.inspection.management.commands.load_recursos import ejecutar_carga

        if not request.user.is_superuser:
            return HttpResponseForbidden("Solo superusuarios pueden importar recursos.")

        context = {
            **self.admin_site.each_context(request),
            "title": "Importar recursos desde JSON",
            "resultado": None,
            "opts": self.model._meta,
        }

        if request.method == "POST":
            archivo = request.FILES.get("json_file")
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

            stats = ejecutar_carga(json_data, dry_run=dry_run)
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
