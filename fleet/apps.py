from django.apps import AppConfig


class FleetConfig(AppConfig):
    name = 'fleet'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        pass  # signals loaded via inventory/apps.py
