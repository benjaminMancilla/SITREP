from django.db import migrations, models


def copiar_categoria_tipo_desde_proposito(apps, schema_editor):
    Recurso = apps.get_model('catalog', 'Recurso')
    for recurso in Recurso.objects.select_related('proposito').all():
        recurso.categoria = recurso.proposito.categoria
        recurso.tipo = recurso.proposito.tipo
        recurso.save(update_fields=['categoria', 'tipo'])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0010_alter_recurso_catalogo_version_notnull'),
    ]

    operations = [
        migrations.AddField(
            model_name='recurso',
            name='categoria',
            field=models.CharField(
                max_length=50,
                choices=[('Seguridad', 'Seguridad'), ('Operacional', 'Operacional')],
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='recurso',
            name='tipo',
            field=models.CharField(
                max_length=50,
                choices=[('Documentacion', 'Documentación'), ('Material', 'Material')],
                null=True,
            ),
        ),
        migrations.RunPython(copiar_categoria_tipo_desde_proposito, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='recurso',
            name='categoria',
            field=models.CharField(
                max_length=50,
                choices=[('Seguridad', 'Seguridad'), ('Operacional', 'Operacional')],
            ),
        ),
        migrations.AlterField(
            model_name='recurso',
            name='tipo',
            field=models.CharField(
                max_length=50,
                choices=[('Documentacion', 'Documentación'), ('Material', 'Material')],
            ),
        ),
        migrations.RemoveField(
            model_name='recurso',
            name='proposito',
        ),
        migrations.DeleteModel(
            name='Proposito',
        ),
    ]
