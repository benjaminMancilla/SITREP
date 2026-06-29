from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sitrep.inventory'

    def ready(self):
        import sitrep.inventory.signals
