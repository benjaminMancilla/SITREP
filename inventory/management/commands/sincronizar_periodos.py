from django.core.management.base import BaseCommand

from inventory.services import MotorPeriodos


class Command(BaseCommand):
    help = "Sincroniza periodos de revision para todas las naves activas."

    def handle(self, *args, **options):
        stats = MotorPeriodos.sincronizar_todas_las_naves()

        self.stdout.write(f"Naves procesadas: {stats['naves_procesadas']}")
        self.stdout.write(f"Periodos creados: {stats['periodos_creados']}")
        self.stdout.write(f"Periodos vencidos: {stats['periodos_vencidos']}")
        self.stdout.write(self.style.SUCCESS("Sincronizacion de periodos completada."))
