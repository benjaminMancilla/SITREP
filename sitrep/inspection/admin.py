from django.contrib import admin

from .models import FichaRegistro, MatrizNaveRecurso, PeriodoRevision


@admin.register(MatrizNaveRecurso)
class MatrizNaveRecursoAdmin(admin.ModelAdmin):
    list_display = (
        "nave", "recurso", "cantidad", "es_visible",
        "ultimo_estado_operativo", "ultimo_estado_operativo_anterior",
        "es_fallo_nuevo",
    )
    readonly_fields = ("ultimo_estado_operativo_en",)
    list_filter = ("nave__naviera", "es_visible")
    search_fields = ("nave__nombre", "recurso__nombre")


@admin.register(FichaRegistro)
class FichaRegistroAdmin(admin.ModelAdmin):
    list_display = ("recurso", "periodo", "usuario", "estado_operativo", "fecha_revision", "fue_modificada")
    list_filter = ("estado_operativo", "periodo__nave__naviera", "periodo__nave")
    search_fields = ("recurso__nombre", "usuario__rut")
    readonly_fields = ("fecha_revision", "modificado_en", "definicion_checklist")

    def fue_modificada(self, obj):
        return obj.modificado_por is not None
    fue_modificada.boolean = True
    fue_modificada.short_description = "Modificada"


admin.site.register(PeriodoRevision)
