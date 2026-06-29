from django.contrib import admin

from .models import Dispositivo, Nave, Tripulacion
from sitrep.inspection.services import MotorReglasSITREP


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


@admin.register(Dispositivo)
class DispositivoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "nave", "naviera", "is_active", "creado_en")
    list_filter = ("naviera", "is_active", "nave")


admin.site.register(Tripulacion)
