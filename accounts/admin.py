from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Naviera, Usuario


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


admin.site.register(Naviera)
