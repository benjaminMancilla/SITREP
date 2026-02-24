from django.db import models
from django.contrib.auth.models import AbstractUser

# TENANT Naviera. Empresa que opera naves y utiliza el sistema para gestionar 
# su material y documentacion portuarias. Cada naviera es un tenant independiente, 
# comparten base de datos pero se hace la distincion por ID de naviera. 
class Naviera(models.Model):
    nombre = models.CharField(max_length=255)
    rut = models.CharField(max_length=10, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre
    
# TENANT Usuario. Cada usuario pertenece a una naviera y tiene un rol (admin, mar, tierra, etc).
class Usuario(AbstractUser):
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
            ('tierra', 'Tierra'),
            ('mar', 'Mar'),
        ],
        default='mar'
    )
    
    class Meta:
        # Permite que una persona pueda ser usuario en varias navieras.
        unique_together = ('naviera', 'rut')  # Asegura que el RUT sea único dentro de cada naviera
        
    def save(self, *args, **kwargs):
        # Inyección de Username Sintético. Django exige un username único global.
        # Lo fabricamos silenciosamente combinando RUT y Naviera ID.
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
    
    def __str__(self):
        nombre_tenant = self.naviera.nombre if self.naviera else "SITREP Global"
        return f"{self.rut} - {nombre_tenant} [{self.rol}]"
