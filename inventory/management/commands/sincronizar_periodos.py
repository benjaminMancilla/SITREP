from django.core.management.base import BaseCommand
from django.db import connections
from django.db import OperationalError
import time

from inventory.services import MotorPeriodos

class Command(BaseCommand):
    help = "Sincroniza periodos de revision para todas las naves activas."

    def handle(self, *args, **options):
        for attempt in range(6):
            try:
                connections['default'].ensure_connection()
                break
            except OperationalError:
                if attempt == 5:
                    self.stdout.write(self.style.ERROR("BD no disponible tras 60s. Abortando."))
                    return
                self.stdout.write(f"BD no disponible, reintentando en 10s... ({attempt + 1}/6)")
                time.sleep(15)

        self.stdout.write("Iniciando motor de sincronización de períodos...")
        stats = MotorPeriodos.sincronizar_todas_las_naves()

        self.stdout.write(f"Naves procesadas: {stats['naves_procesadas']}")
        self.stdout.write(f"Periodos creados: {stats['periodos_creados']}")
        self.stdout.write(f"Periodos vencidos: {stats['periodos_vencidos']}")
        self.stdout.write(f"Periodos con error: {stats['periodos_con_error']}")
        self.stdout.write(f"Naves con error: {stats['naves_con_error']}")
        if stats['naves_con_error'] > 0 or stats['periodos_con_error'] > 0:
            self.stdout.write(self.style.WARNING("Sincronización completada con ERRORES parciales. Revise los logs."))
        else:
            self.stdout.write(self.style.SUCCESS("Sincronizacion de periodos completada."))
