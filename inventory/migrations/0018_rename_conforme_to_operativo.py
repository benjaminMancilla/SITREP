from django.db import migrations, models


def renombrar_conforme_a_operativo(apps, schema_editor):
    PeriodoRevision = apps.get_model("inventory", "PeriodoRevision")
    PeriodoRevision.objects.filter(estado="conforme").update(estado="operativo")


def revertir_operativo_a_conforme(apps, schema_editor):
    PeriodoRevision = apps.get_model("inventory", "PeriodoRevision")
    PeriodoRevision.objects.filter(estado="operativo").update(estado="conforme")


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0017_recurso_created_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="periodorevision",
            name="estado",
            field=models.CharField(
                choices=[
                    ("pendiente", "Pendiente"),
                    ("en_proceso", "En proceso"),
                    ("operativo", "Operativo"),
                    ("observado", "Observado"),
                    ("fallido", "Fallido"),
                    ("omitido", "Omitido"),
                    ("caduco", "Caduco"),
                ],
                default="pendiente",
                max_length=20,
            ),
        ),
        migrations.RunPython(
            renombrar_conforme_a_operativo,
            revertir_operativo_a_conforme,
        ),
    ]
