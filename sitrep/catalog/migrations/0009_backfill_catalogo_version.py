from django.db import migrations


def crear_version_inicial_y_backfill(apps, schema_editor):
    CatalogoVersion = apps.get_model('catalog', 'CatalogoVersion')
    Recurso = apps.get_model('catalog', 'Recurso')
    if not Recurso.objects.exists():
        return
    version = CatalogoVersion.objects.create(
        naviera=None, nave=None, numero=1, creado_por=None,
        nota="Versión inicial — migración desde catálogo estático",
    )
    Recurso.objects.update(
        catalogo_version=version, linaje_raiz=None,
        naviera=None, nave=None, activo=True,
    )


def revertir(apps, schema_editor):
    CatalogoVersion = apps.get_model('catalog', 'CatalogoVersion')
    Recurso = apps.get_model('catalog', 'Recurso')
    Recurso.objects.update(catalogo_version=None)
    CatalogoVersion.objects.filter(naviera=None, nave=None, numero=1).delete()


class Migration(migrations.Migration):
    dependencies = [('catalog', '0008_recurso_add_versioning_fields')]
    operations = [migrations.RunPython(crear_version_inicial_y_backfill, revertir)]
