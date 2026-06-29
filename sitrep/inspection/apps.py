from django.apps import AppConfig


class InspectionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sitrep.inspection'
    label = 'inventory'  # preserva label para migraciones y tablas existentes

    def ready(self):
        import sitrep.inspection.signals
