from django.db import migrations

CANTIDAD_ID = "__cantidad__"


def tipar_requerimientos(apps, schema_editor):
    Recurso = apps.get_model("catalog", "Recurso")
    for recurso in Recurso.objects.all():
        reqs = recurso.requerimientos or []
        if reqs and isinstance(reqs[0], dict):
            continue  # ya migrado

        nuevos = [{"id": texto, "tipo": "estandar", "texto": texto} for texto in reqs]
        if recurso.regla_aplicacion:
            nuevos.append({"id": CANTIDAD_ID, "tipo": "cantidad"})

        if nuevos != reqs:
            recurso.requerimientos = nuevos
            recurso.save(update_fields=["requerimientos"])


def destipar_requerimientos(apps, schema_editor):
    Recurso = apps.get_model("catalog", "Recurso")
    for recurso in Recurso.objects.all():
        reqs = recurso.requerimientos or []
        if not reqs or not isinstance(reqs[0], dict):
            continue

        anteriores = [req["texto"] for req in reqs if req.get("tipo") == "estandar"]
        recurso.requerimientos = anteriores
        recurso.save(update_fields=["requerimientos"])


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(tipar_requerimientos, destipar_requerimientos),
    ]
