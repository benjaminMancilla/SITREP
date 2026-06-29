from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import AbstractUser
from django.db import models


class Naviera(models.Model):
    nombre = models.CharField(max_length=255)
    rut = models.CharField(max_length=10, unique=True)
    slug = models.SlugField(max_length=50, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre


class Usuario(AbstractUser):
    naviera = models.ForeignKey(Naviera, on_delete=models.CASCADE, null=True, blank=True)
    rut = models.CharField(max_length=11)
    email = models.EmailField(null=True, blank=True)
    rol = models.CharField(
        max_length=20,
        choices=[
            ('admin_sitrep', 'Admin SITREP'),
            ('admin_naviera', 'Admin Naviera'),
            ('capitan', 'Admin Nave'),
            ('tierra', 'Tierra'),
            ('mar', 'Mar'),
        ],
        default='mar',
    )
    pin_kiosco = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        unique_together = ('naviera', 'rut')

    def save(self, *args, **kwargs):
        if not self.username:
            nav_id = self.naviera.id if self.naviera else 'global'
            self.username = f"{self.rut}_{nav_id}"
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.is_active = False
        self.save()

    def set_pin(self, raw_pin):
        self.pin_kiosco = make_password(raw_pin)

    def check_pin(self, raw_pin):
        if not self.pin_kiosco:
            return False
        return check_password(raw_pin, self.pin_kiosco)

    def __str__(self):
        nombre_tenant = self.naviera.nombre if self.naviera else "SITREP Global"
        return f"{self.rut} - {nombre_tenant} [{self.rol}]"
