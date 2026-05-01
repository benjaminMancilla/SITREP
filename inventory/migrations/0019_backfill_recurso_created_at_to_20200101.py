import datetime

from django.db import migrations
from django.utils import timezone


def fijar_created_at_recursos_al_20200101(apps, schema_editor):
    Recurso = apps.get_model("inventory", "Recurso")
    fecha_objetivo = timezone.make_aware(datetime.datetime(2020, 1, 1, 0, 0, 0))
    Recurso.objects.all().update(created_at=fecha_objetivo)


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0018_rename_conforme_to_operativo"),
    ]

    operations = [
        migrations.RunPython(
            fijar_created_at_recursos_al_20200101,
            migrations.RunPython.noop,
        ),
    ]
