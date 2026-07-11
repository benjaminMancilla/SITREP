from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import AbstractUser
from django.db import models


class Naviera(models.Model):
    nombre = models.CharField(max_length=255)
    rut = models.CharField(max_length=10, unique=True)
    slug = models.SlugField(max_length=50, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    catalogo_independiente = models.BooleanField(
        default=False,
        help_text="Si es True, esta naviera ignora el catálogo central: solo ve recursos scoped a ella o a sus naves.",
    )

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


class AuditEvent(models.Model):
    """Audit trail: quién accedió/exportó datos con PII. No duplica el dato, solo el acceso."""

    ACCION_CHOICES = [
        ("read", "Lectura"),
        ("export", "Exportación"),
        ("write", "Escritura"),
        ("blocked", "Bloqueado"),
    ]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    naviera = models.ForeignKey(Naviera, on_delete=models.SET_NULL, null=True, blank=True)
    rol = models.CharField(max_length=20, blank=True)
    accion = models.CharField(max_length=10, choices=ACCION_CHOICES)
    recurso = models.CharField(max_length=100)
    detalle = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    session_key = models.CharField(max_length=40, blank=True)
    endpoint = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["usuario", "created_at"]),
        ]

    def __str__(self):
        return f"{self.accion}:{self.recurso} by {self.usuario_id} @ {self.created_at}"
