"""
SeparateDatabaseAndState: mueve Area/Proposito/Periodicidad/Recurso
de inventory a catalog.

state_operations: crea los modelos en catalog.
database_operations: renombra las tablas existentes.

Depende de inventory.0002 (que depende de inventory.0001) para
garantizar que las tablas inventory_* existan antes del rename.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('accounts', '0001_initial'),
        ('inventory', '0002_fleet_split'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Area',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('nombre', models.CharField(max_length=100, unique=True)),
                        ('nombre_tecnico', models.CharField(blank=True, max_length=100, null=True)),
                        ('orden', models.PositiveSmallIntegerField(blank=True, help_text='Orden de visualización del área. Basado en el primer dígito del código de sus recursos.', null=True)),
                        ('token_color', models.CharField(blank=True, help_text="Identificador para la paleta del cliente en el frontend (ej: 'salvamento', 'cubierta')", max_length=30, null=True)),
                    ],
                    options={
                        'verbose_name': 'Área',
                        'verbose_name_plural': 'Áreas',
                        'ordering': ['orden', 'nombre'],
                    },
                ),
                migrations.CreateModel(
                    name='Periodicidad',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('nombre', models.CharField(max_length=100)),
                        ('duracion_dias', models.PositiveIntegerField(default=30, help_text='Duración del período en días. Ej: 7 para semanal, 30 para mensual.')),
                        ('offset_dias', models.PositiveIntegerField(default=1, help_text='Días de margen tras fecha_termino antes de vencer el período. Ej: 1 para semanal, 3 para mensual.')),
                        ('responsabilidad', models.CharField(choices=[('mar', 'Mar'), ('tierra', 'Tierra'), ('todos', 'Todos'), ('ninguno', 'Ninguno')], max_length=20)),
                        ('visibilidad', models.CharField(choices=[('mar', 'Mar'), ('tierra', 'Tierra'), ('todos', 'Todos'), ('ninguno', 'Ninguno')], max_length=20)),
                    ],
                    options={
                        'verbose_name': 'Periodicidad',
                        'verbose_name_plural': 'Periodicidades',
                    },
                ),
                migrations.CreateModel(
                    name='Proposito',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('nombre', models.CharField(max_length=100)),
                        ('categoria', models.CharField(choices=[('Seguridad', 'Seguridad'), ('Operacional', 'Operacional')], max_length=50)),
                        ('tipo', models.CharField(choices=[('Documentacion', 'Documentación'), ('Material', 'Material')], max_length=50)),
                    ],
                    options={
                        'verbose_name': 'Propósito',
                        'verbose_name_plural': 'Propósitos',
                    },
                ),
                migrations.CreateModel(
                    name='Recurso',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('nombre', models.CharField(max_length=255)),
                        ('codigo', models.CharField(blank=True, help_text='Código del recurso según la documentación del cliente (ej: 3.3-Q).', max_length=50, null=True)),
                        ('descripcion', models.TextField(blank=True, help_text='Descripción extendida del recurso. Separada del nombre para nombres limpios.', null=True)),
                        ('created_at', models.DateTimeField(auto_now_add=True, help_text='Fecha de creación del recurso. Usada para excluir recursos del historial de períodos anteriores a su creación.')),
                        ('requerimientos', models.JSONField(default=list, help_text='Ej: ["ser naranjo", "tener cintas"]')),
                        ('regla_aplicacion', models.JSONField(blank=True, help_text='Reglas para atributos dinámicos', null=True)),
                        ('naviera', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='recursos_privados', to='accounts.naviera')),
                        ('area', models.ForeignKey(blank=True, help_text='Área operacional a la que pertenece el recurso (ej: Salvamento, Incendio).', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='recursos', to='catalog.area')),
                        ('periodicidad', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.periodicidad')),
                        ('proposito', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.proposito')),
                    ],
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE inventory_area RENAME TO catalog_area',
                    reverse_sql='ALTER TABLE catalog_area RENAME TO inventory_area',
                ),
                migrations.RunSQL(
                    sql='ALTER TABLE inventory_periodicidad RENAME TO catalog_periodicidad',
                    reverse_sql='ALTER TABLE catalog_periodicidad RENAME TO inventory_periodicidad',
                ),
                migrations.RunSQL(
                    sql='ALTER TABLE inventory_proposito RENAME TO catalog_proposito',
                    reverse_sql='ALTER TABLE catalog_proposito RENAME TO inventory_proposito',
                ),
                migrations.RunSQL(
                    sql='ALTER TABLE inventory_recurso RENAME TO catalog_recurso',
                    reverse_sql='ALTER TABLE catalog_recurso RENAME TO inventory_recurso',
                ),
            ],
        ),
    ]
