from django.conf import settings
from django.db import models


class MatrizNaveRecurso(models.Model):
    nave = models.ForeignKey('fleet.Nave', on_delete=models.CASCADE, related_name='matriz_recursos')
    recurso = models.ForeignKey('catalog.Recurso', on_delete=models.CASCADE)
    cantidad = models.IntegerField()
    es_visible = models.BooleanField(default=True)
    modificado_manualmente = models.BooleanField(default=False)
    ultimo_estado_operativo = models.BooleanField(
        null=True, blank=True, default=None,
        help_text=(
            "Último estado operativo confirmado para este recurso en esta nave. "
            "None = nunca declarado. True = operativo. False = fallado. "
            "Solo se actualiza cuando estado_operativo is not None (no en guardados parciales)."
        ),
    )
    ultimo_estado_operativo_en = models.DateTimeField(null=True, blank=True, default=None,
        help_text="Timestamp de la última vez que ultimo_estado_operativo fue actualizado.")
    es_fallo_nuevo = models.BooleanField(default=False,
        help_text="True si el recurso pasó de operativo/pendiente a fallado en el período actual. Se resetea al cerrar el período.")
    ultimo_estado_operativo_anterior = models.BooleanField(
        null=True, blank=True, default=None,
        help_text=(
            "Snapshot de ultimo_estado_operativo al momento del último cierre de período. "
            "Se actualiza solo al cerrar período, nunca al guardar fichas individuales. "
            "Usado para determinar si un fallo es nuevo comparando contra el estado del período anterior."
        ),
    )

    class Meta:
        unique_together = ('nave', 'recurso')
        verbose_name = "Matriz Nave-Recurso"
        verbose_name_plural = "Matriz Nave-Recurso"

    def __str__(self):
        return f"{self.nave.nombre} - {self.recurso.nombre}: {self.cantidad} unidades"


class PeriodoRevision(models.Model):
    nave = models.ForeignKey('fleet.Nave', on_delete=models.CASCADE, related_name='periodos')
    periodicidad = models.ForeignKey('catalog.Periodicidad', on_delete=models.PROTECT)
    fecha_inicio = models.DateField()
    fecha_termino = models.DateField()
    ESTADOS = [
        ('pendiente', 'Pendiente'), ('en_proceso', 'En proceso'),
        ('cumplido', 'Cumplido'), ('vencido', 'Vencido'),
    ]
    ESTADOS_ABIERTOS    = {'pendiente', 'en_proceso'}
    ESTADOS_CERRADOS    = {'cumplido', 'vencido'}
    ESTADOS_COMPLETOS   = {'cumplido'}
    ESTADOS_INCOMPLETOS = {'vencido'}
    estado = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')

    class Meta:
        verbose_name = "Periodo de Revisión"
        verbose_name_plural = "Periodos de Revisión"

    def __str__(self):
        return f"{self.nave.nombre} | {self.periodicidad.nombre} ({self.fecha_inicio} al {self.fecha_termino})"


class FichaRegistro(models.Model):
    ESTADOS_FICHA = [
        ("pendiente", "Pendiente"), ("en_progreso", "En progreso"), ("completa", "Completa"),
    ]
    periodo = models.ForeignKey(PeriodoRevision, on_delete=models.CASCADE, related_name='fichas')
    recurso = models.ForeignKey('catalog.Recurso', on_delete=models.PROTECT)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha_revision = models.DateTimeField(auto_now_add=True)
    estado_ficha = models.CharField(max_length=20, choices=ESTADOS_FICHA, default="en_progreso",
        help_text="Estado de completitud de la ficha independiente del resultado operativo.")
    estado_operativo = models.BooleanField(null=True, default=None,
        help_text="None=sin determinar, True=operativo, False=con falla. Solo se asigna cuando la ficha está completa.")
    observacion_general = models.TextField(blank=True, default='')
    payload_checklist = models.JSONField(default=dict)
    modificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='fichas_modificadas',
        help_text="Usuario que realizó la última modificación. Null si nunca fue modificada."
    )
    modificado_en = models.DateTimeField(null=True, blank=True,
        help_text="Timestamp de la última modificación.")

    class Meta:
        unique_together = ('periodo', 'recurso')
        verbose_name = "Ficha de Registro"
        verbose_name_plural = "Fichas de Registro"

    def __str__(self):
        if self.estado_operativo is None:
            estado = "PENDIENTE"
        elif self.estado_operativo:
            estado = "OK"
        else:
            estado = "FALLA"
        return f"[{estado}] {self.recurso.nombre} - Periodo: {self.periodo.id}"
