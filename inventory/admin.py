from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Area,
    Dispositivo,
    FichaRegistro,
    MatrizNaveRecurso,
    Nave,
    Naviera,
    Periodicidad,
    PeriodoRevision,
    Proposito,
    Recurso,
    Tripulacion,
    Usuario,
)
from .services import MotorReglasSITREP

from django.http import HttpResponseForbidden
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html
import json


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "nombre_tecnico", "token_color"]
    search_fields = ["nombre", "nombre_tecnico"]
    list_filter = ["token_color"]


@admin.register(Usuario)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Contexto Multi-Tenant", {"fields": ("naviera", "rut", "rol", "pin_kiosco")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Contexto Multi-Tenant", {"fields": ("naviera", "rut", "rol", "pin_kiosco")}),
    )

    list_display = ("rut", "username", "naviera", "rol", "is_active")
    search_fields = ("rut", "username", "email")
    list_filter = ("naviera", "rol", "is_active")

    def save_model(self, request, obj, form, change):
        pin_raw = form.cleaned_data.get("pin_kiosco")
        if pin_raw and not pin_raw.startswith("pbkdf2_"):
            obj.set_pin(pin_raw)
        super().save_model(request, obj, form, change)


@admin.register(Recurso)
class RecursoAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "naviera",
        "proposito",
        "periodicidad",
        "created_at",
        "tiene_regla",
        "num_requerimientos",
    )
    list_filter = ("naviera", "proposito", "periodicidad")
    search_fields = ("nombre",)
    readonly_fields = ("created_at",)

    def tiene_regla(self, obj):
        return bool(obj.regla_aplicacion)

    tiene_regla.boolean = True
    tiene_regla.short_description = "Tiene Regla"

    def num_requerimientos(self, obj):
        return len(obj.requerimientos) if obj.requerimientos else 0

    num_requerimientos.short_description = "# Requerimientos"


@admin.register(MatrizNaveRecurso)
class MatrizNaveRecursoAdmin(admin.ModelAdmin):
    list_display = ("nave", "recurso", "cantidad", "es_visible", "modificado_manualmente")
    list_filter = ("nave__naviera", "es_visible", "modificado_manualmente")
    search_fields = ("nave__nombre", "recurso__nombre")
    actions = ["marcar_como_automatico"]

    def marcar_como_automatico(self, request, queryset):
        queryset.update(modificado_manualmente=False)

    marcar_como_automatico.short_description = "Resetear bandera de modificación manual"


@admin.register(Nave)
class NaveAdmin(admin.ModelAdmin):
    list_display = ("nombre", "matricula", "naviera", "eslora", "is_active")
    list_filter = ("naviera", "is_active")
    actions = ["sincronizar_matriz"]

    def sincronizar_matriz(self, request, queryset):
        for nave in queryset:
            MotorReglasSITREP.sincronizar_matriz_nave(nave)
        self.message_user(request, f"Matriz sincronizada para {queryset.count()} nave(s).")

    sincronizar_matriz.short_description = "Sincronizar MatrizNaveRecurso"


@admin.register(FichaRegistro)
class FichaRegistroAdmin(admin.ModelAdmin):
    list_display = ("recurso", "periodo", "usuario", "estado_operativo", "fecha_revision", "fue_modificada")
    list_filter = ("estado_operativo", "periodo__nave__naviera", "periodo__nave")
    search_fields = ("recurso__nombre", "usuario__rut")
    readonly_fields = ("fecha_revision", "modificado_en")

    def fue_modificada(self, obj):
        return obj.modificado_por is not None

    fue_modificada.boolean = True
    fue_modificada.short_description = "Modificada"

class ImportarRecursosAdmin(admin.ModelAdmin):
    """
    Pseudo-ModelAdmin para registrar la vista de importación de recursos.
    Aparece en el admin bajo "Inventory → Importar recursos".
    """
 
    # Hacemos que apunte a un modelo existente liviano como proxy
    # pero en realidad solo usamos las URLs custom.
 
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
        from inventory.management.commands.load_recursos import ejecutar_carga
        from inventory.models import Naviera
 
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
                return TemplateResponse(
                    request, "admin/inventory/importar_recursos.html", context
                )
 
            try:
                contenido = archivo.read().decode("utf-8")
                json_data = json.loads(contenido)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                context["error"] = f"Archivo inválido: {e}"
                return TemplateResponse(
                    request, "admin/inventory/importar_recursos.html", context
                )
 
            naviera = None
            if scope == "naviera" and naviera_id:
                try:
                    naviera = Naviera.objects.get(pk=naviera_id)
                except Naviera.DoesNotExist:
                    context["error"] = "Naviera no encontrada."
                    return TemplateResponse(
                        request, "admin/inventory/importar_recursos.html", context
                    )
 
            stats = ejecutar_carga(json_data, naviera=naviera, dry_run=dry_run)
            context["resultado"] = stats
            context["dry_run"] = dry_run
 
        return TemplateResponse(
            request, "admin/inventory/importar_recursos.html", context
        )
 
    def has_module_perms(self, user):
        return user.is_superuser
 
    def has_add_permission(self, request):
        return False
 
    def has_change_permission(self, request, obj=None):
        return False
 
    def has_delete_permission(self, request, obj=None):
        return False
 
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser


admin.site.register(Naviera)
admin.site.register(Tripulacion)
admin.site.register(Dispositivo)
admin.site.register(Proposito, ImportarRecursosAdmin)
admin.site.register(Periodicidad)
admin.site.register(PeriodoRevision)
