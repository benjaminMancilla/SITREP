import secrets

from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.db import models
from django.db.models import Q, UniqueConstraint

from core.tenant import TenantManager


class Nave(models.Model):
    naviera = models.ForeignKey('accounts.Naviera', on_delete=models.CASCADE)
    nombre = models.CharField(max_length=255)
    matricula = models.CharField(max_length=30)
    eslora = models.DecimalField(max_digits=6, decimal_places=2)
    arqueo_bruto = models.IntegerField()
    capacidad_personas = models.IntegerField()
    is_active = models.BooleanField(default=True, help_text='Si es False, la nave fue vendida o dada de baja')
    agregado_en = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=['naviera', 'matricula'],
                condition=Q(is_active=True),
                name='unica_matricula_activa_por_naviera',
            )
        ]

    def delete(self, *args, **kwargs):
        self.is_active = False
        self.save()

    def __str__(self):
        estado = "" if self.is_active else " [INACTIVA]"
        return f"{self.nombre} ({self.matricula}){estado}"


class Dispositivo(models.Model):
    naviera = models.ForeignKey('accounts.Naviera', on_delete=models.CASCADE, related_name='dispositivos')
    nave = models.ForeignKey(Nave, on_delete=models.CASCADE, related_name='dispositivos')
    nombre = models.CharField(max_length=100, help_text='Ej: Tablet Puente Mando, PC Sala Máquinas')
    token_hash = models.CharField(max_length=128, blank=True, null=True, help_text='Hash criptográfico del token físico')
    is_active = models.BooleanField(default=True, help_text='Apagar si la tablet se pierde o se daña')
    creado_en = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    def generar_nuevo_token(self):
        token_plano = secrets.token_urlsafe(32)
        self.token_hash = make_password(token_plano)
        return token_plano

    def verificar_token(self, token_plano):
        if not self.token_hash:
            return False
        return check_password(token_plano, self.token_hash)

    def __str__(self):
        estado = "" if self.is_active else " [BLOQUEADO]"
        return f"[{self.nave.nombre}] {self.nombre}{estado}"


class Tripulacion(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='asignaciones_naves')
    nave = models.ForeignKey(Nave, on_delete=models.CASCADE, related_name='tripulantes')
    asignado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('usuario', 'nave')
        verbose_name = "Tripulación"
        verbose_name_plural = "Tripulaciones"

    def __str__(self):
        return f"{self.usuario.rut} -> {self.nave.nombre}"
