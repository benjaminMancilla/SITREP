"""
SeparateDatabaseAndState: mueve Nave/Dispositivo/Tripulacion de inventory a fleet.

state_operations: le dice a Django que estos modelos ahora viven en fleet.
database_operations: renombra las tablas existentes en la DB.

Para DB vacía (tests/nuevo deploy): inventory/0001 crea inventory_nave primero
(dependencia declarada), luego esta migración la renombra a fleet_nave.
Para Railway (tablas ya existentes): misma operación, mismas tablas.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('accounts', '0001_initial'),
        ('inventory', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Nave',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('nombre', models.CharField(max_length=255)),
                        ('matricula', models.CharField(max_length=30)),
                        ('eslora', models.DecimalField(decimal_places=2, max_digits=6)),
                        ('arqueo_bruto', models.IntegerField()),
                        ('capacidad_personas', models.IntegerField()),
                        ('is_active', models.BooleanField(default=True, help_text='Si es False, la nave fue vendida o dada de baja')),
                        ('agregado_en', models.DateTimeField(auto_now_add=True)),
                        ('naviera', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='accounts.naviera')),
                    ],
                ),
                migrations.AddConstraint(
                    model_name='nave',
                    constraint=models.UniqueConstraint(
                        condition=models.Q(('is_active', True)),
                        fields=('naviera', 'matricula'),
                        name='unica_matricula_activa_por_naviera',
                    ),
                ),
                migrations.CreateModel(
                    name='Dispositivo',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('nombre', models.CharField(help_text='Ej: Tablet Puente Mando, PC Sala Máquinas', max_length=100)),
                        ('token_hash', models.CharField(blank=True, help_text='Hash criptográfico del token físico', max_length=128, null=True)),
                        ('is_active', models.BooleanField(default=True, help_text='Apagar si la tablet se pierde o se daña')),
                        ('creado_en', models.DateTimeField(auto_now_add=True)),
                        ('naviera', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dispositivos', to='accounts.naviera')),
                        ('nave', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dispositivos', to='fleet.nave')),
                    ],
                ),
                migrations.CreateModel(
                    name='Tripulacion',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('asignado_en', models.DateTimeField(auto_now_add=True)),
                        ('nave', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tripulantes', to='fleet.nave')),
                        ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='asignaciones_naves', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'verbose_name': 'Tripulación',
                        'verbose_name_plural': 'Tripulaciones',
                        'unique_together': {('usuario', 'nave')},
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE inventory_nave RENAME TO fleet_nave',
                    reverse_sql='ALTER TABLE fleet_nave RENAME TO inventory_nave',
                ),
                migrations.RunSQL(
                    sql='ALTER TABLE inventory_dispositivo RENAME TO fleet_dispositivo',
                    reverse_sql='ALTER TABLE fleet_dispositivo RENAME TO inventory_dispositivo',
                ),
                migrations.RunSQL(
                    sql='ALTER TABLE inventory_tripulacion RENAME TO fleet_tripulacion',
                    reverse_sql='ALTER TABLE fleet_tripulacion RENAME TO inventory_tripulacion',
                ),
            ],
        ),
    ]
