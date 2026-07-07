from django.db import migrations


def reset_fichas_en_progreso(apps, schema_editor):
    FichaRegistro = apps.get_model('inspection', 'FichaRegistro')
    FichaRegistro.objects.filter(
        estado_ficha='en_progreso',
        periodo__estado__in=['cumplido', 'vencido'],
    ).update(estado_ficha='pendiente')


class Migration(migrations.Migration):

    dependencies = [
        ('inspection', '0004_collapse_periodo_estados'),
    ]

    operations = [
        migrations.RunPython(reset_fichas_en_progreso, migrations.RunPython.noop),
    ]
