"""
SeparateDatabaseAndState: limpia el estado de inventory post-split de fleet.

state_operations: actualiza los FK de MatrizNaveRecurso y PeriodoRevision
para que apunten a fleet.Nave, y elimina Nave/Dispositivo/Tripulacion del
estado de inventory.

database_operations: vacías — las tablas ya fueron renombradas en fleet/0001.
Los FK columns (nave_id) siguen intactos; PostgreSQL y SQLite rastrean FK
por OID/rowid, no por nombre de tabla.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0001_initial'),
        ('inventory', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='matriznaverecurso',
                    name='nave',
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='matriz_recursos',
                        to='fleet.nave',
                    ),
                ),
                migrations.AlterField(
                    model_name='periodorevision',
                    name='nave',
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='periodos',
                        to='fleet.nave',
                    ),
                ),
                migrations.DeleteModel('Dispositivo'),
                migrations.DeleteModel('Tripulacion'),
                migrations.DeleteModel('Nave'),
            ],
            database_operations=[],
        ),
    ]
