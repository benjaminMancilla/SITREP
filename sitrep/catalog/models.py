from django.conf import settings
from django.db import models, transaction


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
    regla_aplicacion = models.JSONField(
        null=True, blank=True,
        help_text=(
            'Motor de reglas: calcula, por nave, tanto la CANTIDAD del requerimiento '
            '"cantidad" como la VISIBILIDAD del recurso (es_visible en la matriz). '
            'Ej: {"version": 1, "atributo": "eslora", "condiciones": [{"operador": "<=", '
            '"valor": 10, "resultado_cantidad": 0, "resultado_visible": false}], '
            '"fallback_cantidad": 2, "fallback_visible": true}. '
            '"version" es opcional (se asume 1 si falta) — existe para que futuras '
            'versiones del motor no rompan reglas viejas. '
            'Sin regla (null): cantidad=0 y es_visible=True para toda nave.'
        ),
    )

    def __str__(self):
        return self.nombre


class CatalogoVersion(models.Model):
    naviera = models.ForeignKey(
        'accounts.Naviera', null=True, blank=True,
        on_delete=models.CASCADE, related_name='versiones_catalogo',
        help_text="Null = cadena central. Si nave está seteado, naviera se deriva de nave.naviera.",
    )
    nave = models.ForeignKey(
        'fleet.Nave', null=True, blank=True,
        on_delete=models.CASCADE, related_name='versiones_catalogo',
        help_text="Null = esta versión no es de una nave específica (central o naviera).",
    )
    numero = models.PositiveIntegerField(
        help_text="Secuencia independiente por scope (central / naviera / nave), empieza en 1.",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='catalogo_versiones_creadas',
        help_text="Null: sin editor asignado (no existe rol editor todavía).",
    )
    nota = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['naviera_id', 'nave_id', 'numero']
        constraints = [
            models.UniqueConstraint(
                fields=['naviera', 'nave', 'numero'],
                name='unica_numero_por_scope_catalogo',
                nulls_distinct=False,
            ),
        ]
        verbose_name = "Versión de Catálogo"
        verbose_name_plural = "Versiones de Catálogo"

    def __str__(self):
        scope = self.nave.nombre if self.nave_id else (self.naviera.nombre if self.naviera_id else "Central")
        return f"{scope} v{self.numero}"

    @classmethod
    def crear_para_scope(cls, *, naviera=None, nave=None, creado_por=None, nota=""):
        if nave is not None and naviera is None:
            naviera = nave.naviera
        if nave is not None and naviera is not None and nave.naviera_id != naviera.id:
            raise ValueError("nave.naviera no coincide con naviera dada.")
        with transaction.atomic():
            ultimo = (
                cls.objects.select_for_update()
                .filter(naviera=naviera, nave=nave)
                .order_by('-numero')
                .first()
            )
            numero = (ultimo.numero if ultimo else 0) + 1
            return cls.objects.create(
                naviera=naviera, nave=nave, numero=numero,
                creado_por=creado_por, nota=nota,
            )
