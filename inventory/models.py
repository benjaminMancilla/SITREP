from django.conf import settings
from django.db import models


class Proposito(models.Model):
    nombre = models.CharField(max_length=100)
    categoria = models.CharField(
        max_length=50,
        choices=[('Seguridad', 'Seguridad'), ('Operacional', 'Operacional')]
    )
    tipo = models.CharField(
        max_length=50,
        choices=[('Documentacion', 'Documentación'), ('Material', 'Material')]
    )

    class Meta:
        verbose_name = "Propósito"
        verbose_name_plural = "Propósitos"

    def __str__(self):
        return f" {self.tipo} de {self.nombre} ({self.categoria})"


class Area(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    nombre_tecnico = models.CharField(max_length=100, unique=False, null=True, blank=True)
    orden = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Orden de visualización del área. Basado en el primer dígito del código de sus recursos.",
    )
    token_color = models.CharField(
        max_length=30, blank=True, null=True,
        help_text="Identificador para la paleta del cliente en el frontend (ej: 'salvamento', 'cubierta')"
    )

    class Meta:
        ordering = ["orden", "nombre"]
        verbose_name = "Área"
        verbose_name_plural = "Áreas"

    def __str__(self):
        return self.nombre

    @property
    def css_classes(self):
        mapa = {
            'telecom': 'bg-emerald-50 border-emerald-200 text-emerald-700',
            'navegacion': 'bg-sky-50 border-sky-200 text-sky-700',
            'maquinas': 'bg-orange-50 border-orange-200 text-orange-700',
            'gobierno': 'bg-amber-50 border-amber-200 text-amber-700',
            'contaminacion': 'bg-slate-100 border-slate-300 text-slate-700',
            'salvamento': 'bg-yellow-50 border-yellow-300 text-yellow-800',
            'inundacion': 'bg-fuchsia-50 border-fuchsia-200 text-fuchsia-700',
            'incendio': 'bg-rose-50 border-rose-200 text-rose-700',
            'general': 'bg-white border-surface-border text-ink-secondary',
        }
        return mapa.get(self.token_color, mapa['general'])


class Periodicidad(models.Model):
    nombre = models.CharField(max_length=100)
    duracion_dias = models.PositiveIntegerField(
        default=30,
        help_text="Duración del período en días. Ej: 7 para semanal, 30 para mensual."
    )
    offset_dias = models.PositiveIntegerField(
        default=1,
        help_text="Días de margen tras fecha_termino antes de vencer el período. Ej: 1 para semanal, 3 para mensual."
    )
    OPCIONES_AUDITORIA = [('mar', 'Mar'), ('tierra', 'Tierra'), ('todos', 'Todos'), ('ninguno', 'Ninguno')]
    responsabilidad = models.CharField(max_length=20, choices=OPCIONES_AUDITORIA)
    visibilidad = models.CharField(max_length=20, choices=OPCIONES_AUDITORIA)

    class Meta:
        verbose_name = "Periodicidad"
        verbose_name_plural = "Periodicidades"

    def __str__(self):
        return self.nombre


class Recurso(models.Model):
    naviera = models.ForeignKey('accounts.Naviera', on_delete=models.CASCADE, null=True, blank=True, related_name='recursos_privados')
    proposito = models.ForeignKey(Proposito, on_delete=models.PROTECT)
    periodicidad = models.ForeignKey(Periodicidad, on_delete=models.PROTECT)
    area = models.ForeignKey(
        Area, on_delete=models.SET_NULL, null=True, blank=True, related_name="recursos",
        help_text="Área operacional a la que pertenece el recurso (ej: Salvamento, Incendio).",
    )
    nombre = models.CharField(max_length=255)
    codigo = models.CharField(max_length=50, null=True, blank=True,
        help_text="Código del recurso según la documentación del cliente (ej: 3.3-Q).")
    descripcion = models.TextField(null=True, blank=True,
        help_text="Descripción extendida del recurso. Separada del nombre para nombres limpios.")
    created_at = models.DateTimeField(auto_now_add=True,
        help_text="Fecha de creación del recurso. Usada para excluir recursos del historial de períodos anteriores a su creación.")
    requerimientos = models.JSONField(default=list, help_text='Ej: ["ser naranjo", "tener cintas"]')
    regla_aplicacion = models.JSONField(null=True, blank=True, help_text='Reglas para atributos dinámicos')

    def __str__(self):
        tipo = "Global" if not self.naviera else f"Privado ({self.naviera.nombre})"
        return f"{self.nombre} [{tipo}]"


class MatrizNaveRecurso(models.Model):
    nave = models.ForeignKey('fleet.Nave', on_delete=models.CASCADE, related_name='matriz_recursos')
    recurso = models.ForeignKey(Recurso, on_delete=models.CASCADE)
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
    periodicidad = models.ForeignKey(Periodicidad, on_delete=models.PROTECT)
    fecha_inicio = models.DateField()
    fecha_termino = models.DateField()
    ESTADOS = [
        ('pendiente', 'Pendiente'), ('en_proceso', 'En proceso'),
        ('operativo', 'Operativo'), ('observado', 'Observado'),
        ('fallido', 'Fallido'), ('omitido', 'Omitido'), ('caduco', 'Caduco'),
    ]
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
    recurso = models.ForeignKey(Recurso, on_delete=models.PROTECT)
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
