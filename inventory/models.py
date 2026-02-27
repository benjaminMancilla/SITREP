import uuid

from django.db import models
from django.db.models import Q, UniqueConstraint
from django.contrib.auth.models import AbstractUser

from django.contrib.auth.hashers import make_password, check_password

# ==========================================
# CORE & AISLAMIENTO MULTI-TENANT
# ==========================================

class Naviera(models.Model):
    """
    TENANT Naviera. Empresa que opera naves y utiliza el sistema para gestionar 
    su material y documentacion portuarias. Cada naviera es un tenant independiente, 
    comparten base de datos pero se hace la distincion por ID de naviera.
    """
    nombre = models.CharField(max_length=255)
    rut = models.CharField(max_length=10, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre


class Usuario(AbstractUser):
    """
    TENANT Usuario. Cada usuario pertenece a una naviera y tiene un rol (admin, mar, tierra, etc).
    """
    # Relacion con Naviera para identificar a que tenant pertenece cada usuario
    # Se permite null/blank para facilitar la creación de superusuarios sin asignar naviera
    naviera = models.ForeignKey(Naviera, on_delete=models.CASCADE, null=True, blank=True)
    # Identificador basado en RUT para usuarios, con email opcional
    # Rut admite XXX.XXX.XXX-X max_length=11 (sin contar puntos) para cubrir todos los formatos
    rut = models.CharField(max_length=11, help_text="RUT del tripulante o administrador")
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
        default='mar'
    )
    
    pin_kiosco = models.CharField(
        max_length=128, 
        null=True, 
        blank=True, 
        help_text="PIN cifrado para acceso en Kiosco"
    )
    
    class Meta:
        # Permite que una persona pueda ser usuario en varias navieras.
        unique_together = ('naviera', 'rut')  # Asegura que el RUT sea único dentro de cada naviera
        
    def save(self, *args, **kwargs):
        """
        Inyección de Username Sintético. Django exige un username único global.
        Lo fabricamos silenciosamente combinando RUT y Naviera ID.
        """
        if not self.username:
            nav_id = self.naviera.id if self.naviera else 'global'
            self.username = f"{self.rut}_{nav_id}"
            
        super().save(*args, **kwargs)
        
    # Blindaje Soft Delete
    def delete(self, *args, **kwargs):
        """
        Intercepta la orden de eliminación de la base de datos.
        En lugar de borrar la fila (DELETE), la apaga lógicamente (UPDATE).
        """
        self.is_active = False
        self.save()
        
    def set_pin(self, raw_pin):
        """
        Método para establecer el PIN del kiosco, cifrándolo antes de guardarlo.
        """
        self.pin_kiosco = make_password(raw_pin)
        
    def check_pin(self, raw_pin):
        """Devuelve True si el PIN ingresado coincide con el hash guardado."""
        if not self.pin_kiosco:
            return False
        return check_password(raw_pin, self.pin_kiosco)
    
    def __str__(self):
        nombre_tenant = self.naviera.nombre if self.naviera else "SITREP Global"
        return f"{self.rut} - {nombre_tenant} [{self.rol}]"


class Nave(models.Model):
    """
    Embarcaciones fisicas que poseen los clientes (navieras) y que se gestionan en el sistema.
    Las propiedades fisicas de la nave se almacenan en este modelo, y son vitales para la generacion
    automatica de la ficha de recursos de la nave.
    """
    # Cada nave pertenece a solo una naviera
    naviera = models.ForeignKey(Naviera, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=255)
    matricula = models.CharField(max_length=30)
    
    # Atributos físicos
    eslora = models.DecimalField(max_digits=6, decimal_places=2)
    arqueo_bruto = models.IntegerField()
    capacidad_personas = models.IntegerField()
    
    # Blindaje Soft Delete
    is_active = models.BooleanField(default=True, help_text="Si es False, la nave fue vendida o dada de baja")
    agregado_en = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        constraints = [
            UniqueConstraint(
                fields=['naviera', 'matricula'],
                condition=Q(is_active=True),
                name='unica_matricula_activa_por_naviera'
            )
        ]
    
    def delete(self, *args, **kwargs):
        """
        Soft Delete para evitar destruir el historial de inspecciones de la naviera
        cuando venden o dan de baja una embarcación.
        """
        self.is_active = False
        self.save()

    def __str__(self):
        estado = "" if self.is_active else " [INACTIVA]"
        return f"{self.nombre} ({self.matricula}){estado}"


class Tripulacion(models.Model):
    """
    Tripulación asignada a cada nave. Permite saber qué usuarios (marineros) 
    están asignados a qué naves, y cuándo se hizo la asignación. Vital para 
    auditar que marineros pueden acceder a los recursos de cada nave.
    """
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='asignaciones_naves')
    nave = models.ForeignKey(Nave, on_delete=models.CASCADE, related_name='tripulantes')
    asignado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Un marinero no puede ser asignado dos veces a la misma nave
        unique_together = ('usuario', 'nave')
        verbose_name = "Tripulación"
        verbose_name_plural = "Tripulaciones"

    def __str__(self):
        return f"{self.usuario.rut} -> {self.nave.nombre}"

    
class Dispositivo(models.Model):
    """
    HARDWARE BINDING: Representa un equipo físico autorizado (Tablet, PC) 
    instalado en una nave o instalación de la naviera.
    """
    naviera = models.ForeignKey(Naviera, on_delete=models.CASCADE, related_name='dispositivos')
    nave = models.ForeignKey(Nave, on_delete=models.CASCADE, null=True, blank=True, related_name='dispositivos')
    
    nombre = models.CharField(max_length=100, help_text="Ej: Tablet Puente Mando, PC Sala Máquinas")
    # Este token se inyectará en el navegador del dispositivo físico
    token_autorizacion = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    is_active = models.BooleanField(default=True, help_text="Apagar si la tablet se pierde o se daña")
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        ubicacion = self.nave.nombre if self.nave else "Tierra"
        estado = "" if self.is_active else " [BLOQUEADO]"
        return f"[{ubicacion}] {self.nombre}{estado}"
    
# ==========================================
# DICCIONARIOS Y CATÁLOGO HÍBRIDO
# ==========================================

class Proposito(models.Model):
    """
    Definición de Propósitos para los recursos (según la organización del cliente). 
    Cada recurso debe tener un propósito que lo clasifique, este determina su función
    dentro del sistema. La categoría es simbolica, el tipo tiene implicaciones en la ficha de recursos.
    """
    nombre = models.CharField(max_length=100)
    categoria = models.CharField(
        max_length=50, 
        choices=[
            ('Seguridad', 'Seguridad'), 
            ('Operacional', 'Operacional')
        ]
    )
    tipo = models.CharField(
        max_length=50, 
        choices=[
            ('Documentacion', 'Documentación'), 
            ('Material', 'Material')
        ]
    )

    class Meta:
        verbose_name = "Propósito"
        verbose_name_plural = "Propósitos"

    def __str__(self):
        return f" {self.tipo} de {self.nombre} ({self.categoria})"


class Periodicidad(models.Model):
    """
    Tipo de periodicidades (diaria, semanal, mensual, etc) que pueden tener los recursos.
    Estas son GLOBALES, por lo que todos los tenant comparten las mismas periodicidades.
    Los recursos de cada periodicidad cambian segun responsabilidad (mar/tierra) y visibilidad (mar/tierra).
    Las responsabilidad indica quien puede agregar registros de cierto recurso.
    Las periodicidades mas largas (anuales, bianuales) suelen ser responsabilidad de tierra, 
    mientras que las mas cortas (diarias, semanales) son responsabilidad de mar.
    La visibilidad determina quién ve el recurso en la ficha de recursos.
    Se suele usar la visibilidad para ocultar recursos que solo tierra debe ver a los de mar.
    """
    nombre = models.CharField(max_length=100)
    OPCIONES_AUDITORIA = [('mar', 'Mar'), ('tierra', 'Tierra'), ('todos', 'Todos'), ('ninguno', 'Ninguno')]
    responsabilidad = models.CharField(max_length=20, choices=OPCIONES_AUDITORIA)
    visibilidad = models.CharField(max_length=20, choices=OPCIONES_AUDITORIA)

    class Meta:
        verbose_name = "Periodicidad"
        verbose_name_plural = "Periodicidades"

    def __str__(self):
        return self.nombre


"""
Ejemplo de regla_aplicacion:
{
  "atributo": "eslora",
  "condiciones": [
    {
      "operador": "<=", 
      "valor": 10, 
      "resultado_cantidad": 0, 
      "resultado_visible": false
    },
    {
      "operador": "<=", 
      "valor": 50, 
      "resultado_cantidad": 2, 
      "resultado_visible": true
    },
    {
      "operador": ">", 
      "valor": 50, 
      "resultado_cantidad": 4, 
      "resultado_visible": true
    }
  ],
  "fallback_cantidad": 0,
  "fallback_visible": false
}
"""

class Recurso(models.Model):
    """
    Recurso: Elemento o documento que se gestiona en el sistema. 
    
    Puede ser un recurso físico (ej: extintor) o digital (ej: certificado de seguridad). 
    Un recurso tiene un propósito (ej: seguridad), una periodicidad (ej: mensual) y 
    una visibilidad (mar/tierra).

    Los recursos pueden ser globales (visibles para todas las navieras) o privados 
    (visibles solo para la naviera que los creó).

    Un recurso puede tener requerimientos (ej: "ser naranjo", "tener cintas"), cada uno de
    estos debe ser revisado para considerar que el recurso está completo.

    Recursos del tipo documentación suelen NO tener requerimientos, mientras que los de 
    tipo material SÍ suelen tener requerimientos.

    Los recursos poseen características que dependen de la nave (ej: eslora, arqueo, etc), 
    Estas características (cantidad, es_visible, etc) dependen de regla_aplicacion.
    """
    # Aislamiento Híbrido: Null = Global (SITREP), ID = Privado (Naviera)
    naviera = models.ForeignKey(Naviera, on_delete=models.CASCADE, null=True, blank=True, related_name='recursos_privados')
    
    # PROTECT: No permitimos borrar un propósito si hay recursos usándolo.
    proposito = models.ForeignKey(Proposito, on_delete=models.PROTECT)
    periodicidad = models.ForeignKey(Periodicidad, on_delete=models.PROTECT)
    
    nombre = models.CharField(max_length=255)
    
    # EL CONTRATO DINÁMICO
    requerimientos = models.JSONField(default=list, help_text='Ej: ["ser naranjo", "tener cintas"]')
    regla_aplicacion = models.JSONField(null=True, blank=True, help_text='Reglas para atributos dinámicos')

    def __str__(self):
        tipo = "Global" if not self.naviera else f"Privado ({self.naviera.nombre})"
        return f"{self.nombre} [{tipo}]"
    
# ==========================================
# RELACION RECURSO-NAVE SEGÚN REGLAS
# ==========================================

class MatrizNaveRecurso(models.Model):
    """
    Tabla intermedia que asigna recursos a naves según las reglas de aplicación definidas en cada recurso.
    Esta tabla define la Ficha de Recursos de cada nave, indicando qué recursos le corresponden según
    sus atributos físicos y las reglas de aplicación. Se puede actualizar manualmente para casos especiales, 
    pero su función principal es ser generada automáticamente.
    Los casos especiales (modificados manualmente) no pueden ser sobreescritos por la generación automática, 
    o por updates masivos, esto hace que las excepciones se mantengan a salvo.
    """
    nave = models.ForeignKey(Nave, on_delete=models.CASCADE, related_name='matriz_recursos')
    recurso = models.ForeignKey(Recurso, on_delete=models.CASCADE)
    
    cantidad = models.IntegerField()
    es_visible = models.BooleanField(default=True)
    
    # Bandera de Auditoría
    modificado_manualmente = models.BooleanField(default=False)

    class Meta:
        # Constraint de integridad crítico
        unique_together = ('nave', 'recurso')
        verbose_name = "Matriz Nave-Recurso"
        verbose_name_plural = "Matriz Nave-Recurso"

    def __str__(self):
        return f"{self.nave.nombre} - {self.recurso.nombre}: {self.cantidad} unidades"
    
# ==========================================
# EVENTOS TRANSACCIONALES
# ==========================================

class PeriodoRevision(models.Model):
    """
    Indica el periodo real de revision (basado en una periodicidad) que se le hizo a una nave.
    Cada vez que se hace una revision a una nave, se genera un nuevo PeriodoRevision con su fecha de inicio
    y termino, las fechas no tienen porque coincidir entre naves.
    """
    nave = models.ForeignKey(Nave, on_delete=models.CASCADE, related_name='periodos')
    periodicidad = models.ForeignKey(Periodicidad, on_delete=models.PROTECT)
    fecha_inicio = models.DateField()
    fecha_termino = models.DateField()
    
    ESTADOS = [('abierto', 'Abierto'), ('cerrado', 'Cerrado'), ('vencido', 'Vencido')]
    estado = models.CharField(max_length=20, choices=ESTADOS, default='abierto')
    
    class Meta:
        verbose_name = "Periodo de Revisión"
        verbose_name_plural = "Periodos de Revisión"

    def __str__(self):
        return f"{self.nave.nombre} | {self.periodicidad.nombre} ({self.fecha_inicio} al {self.fecha_termino})"
    

class FichaRegistro(models.Model):
    """
    Ficha de Registro: Entidad que guarda la revision del inventario de recursos para una nave
    en un periodo de revision específico. Cada vez que se hace una revision, se genera una ficha de registro.
    En la ficha se guarda el estado del recurso para una nave (operativo o fallado), una observacion general, 
    y un payload dinámico con el detalle de cada requerimiento de cada recurso (estado y observacion).

    Un recurso solo puede estar operativo si TODOS sus requerimientos están operativos, pero un
    recurso puede estar FALLADO aunque se cumplan todos los requerimientos.
    """
    periodo = models.ForeignKey(PeriodoRevision, on_delete=models.CASCADE, related_name='fichas')
    recurso = models.ForeignKey(Recurso, on_delete=models.PROTECT)
    # PROTECT al usuario: Mantiene el historial aunque el marinero se vaya (se complementa con el Soft Delete)
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT) 
    fecha_revision = models.DateTimeField(auto_now_add=True)

    # Datos de la ficha
    estado_operativo = models.BooleanField()
    observacion_general = models.TextField(blank=True, default='')
    
    # DETALLE DINÁMICO
    payload_checklist = models.JSONField(default=dict)

    class Meta:
        # Una ficha única por recurso dentro de un periodo específico
        unique_together = ('periodo', 'recurso')
        verbose_name = "Ficha de Registro"
        verbose_name_plural = "Fichas de Registro"

    def __str__(self):
        estado = "OK" if self.estado_operativo else "FALLA"
        return f"[{estado}] {self.recurso.nombre} - Periodo: {self.periodo.id}"

