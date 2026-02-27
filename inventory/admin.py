from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    Naviera, Usuario, Nave, Tripulacion, Dispositivo,
    Proposito, Periodicidad, Recurso, 
    MatrizNaveRecurso, PeriodoRevision, FichaRegistro
)

@admin.register(Usuario)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Contexto Multi-Tenant', {'fields': ('naviera', 'rut', 'rol')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Contexto Multi-Tenant', {'fields': ('naviera', 'rut', 'rol')}),
    )
    
    list_display = ('rut', 'username', 'naviera', 'rol', 'is_active')
    search_fields = ('rut', 'username', 'email')
    list_filter = ('naviera', 'rol', 'is_active')

admin.site.register(Naviera)
admin.site.register(Nave)
admin.site.register(Tripulacion)
admin.site.register(Dispositivo)
admin.site.register(Proposito)
admin.site.register(Periodicidad)
admin.site.register(Recurso)
admin.site.register(MatrizNaveRecurso)
admin.site.register(PeriodoRevision)
admin.site.register(FichaRegistro)
