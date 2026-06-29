"""
SeparateDatabaseAndState: limpia el estado de inventory post-split de catalog.

Actualiza los FK de PeriodoRevision, MatrizNaveRecurso y FichaRegistro para
que apunten a catalog.*, y elimina Area/Proposito/Periodicidad/Recurso del
estado de inventory.

database_operations vacías — las tablas ya fueron renombradas en catalog/0001.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0001_initial'),
        ('inventory', '0002_fleet_split'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='periodorevision',
                    name='periodicidad',
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to='catalog.periodicidad',
                    ),
                ),
                migrations.AlterField(
                    model_name='matriznaverecurso',
                    name='recurso',
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to='catalog.recurso',
                    ),
                ),
                migrations.AlterField(
                    model_name='ficharegistro',
                    name='recurso',
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to='catalog.recurso',
                    ),
                ),
                # Recurso primero — FK a Proposito/Periodicidad/Area
                migrations.DeleteModel('Recurso'),
                migrations.DeleteModel('Area'),
                migrations.DeleteModel('Proposito'),
                migrations.DeleteModel('Periodicidad'),
            ],
            database_operations=[],
        ),
    ]
