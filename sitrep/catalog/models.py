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
    nombre_tecnico = models.CharField(max_length=100, null=True, blank=True)
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
    naviera = models.ForeignKey(
        'accounts.Naviera', on_delete=models.CASCADE,
        null=True, blank=True, related_name='recursos_privados'
    )
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
    requerimientos = models.JSONField(
        default=list,
        help_text=(
            'Lista de requerimientos tipados. Ej: '
            '[{"id": "vigencia", "tipo": "estandar", "texto": "Vigencia vigente"}, '
            '{"id": "condicion_1", "tipo": "condicion"}, '
            '{"id": "__cantidad__", "tipo": "cantidad"}]. '
            'Tipos: "estandar" (texto fijo del editor), "condicion" (label fijo "Condición."), '
            '"cantidad" (label calculado por el motor de reglas, sin texto).'
        ),
    )
    regla_aplicacion = models.JSONField(null=True, blank=True, help_text='Reglas para atributos dinámicos')

    def __str__(self):
        tipo = "Global" if not self.naviera else f"Privado ({self.naviera.nombre})"
        return f"{self.nombre} [{tipo}]"
