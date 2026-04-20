import logging
import time

from django.core.management.base import BaseCommand
from django.db import OperationalError, connections

from inventory.models import Nave
from inventory.services import MotorReglasSITREP

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sincroniza la matriz de recursos para naves activas o una nave específica."

    def add_arguments(self, parser):
        parser.add_argument(
            "--nave-id",
            type=int,
            dest="nave_id",
            help="ID de una nave específica a sincronizar.",
        )

    def handle(self, *args, **options):
        for attempt in range(6):
            try:
                connections["default"].ensure_connection()
                break
            except OperationalError:
                if attempt == 5:
                    self.stdout.write(self.style.ERROR("BD no disponible tras 60s. Abortando."))
                    return
                self.stdout.write(f"BD no disponible, reintentando en 15s... ({attempt + 1}/6)")
                time.sleep(15)

        stats = {
            "naves_procesadas": 0,
            "naves_con_error": 0,
            "recursos_creados": 0,
            "recursos_actualizados": 0,
            "recursos_omitidos": 0,
            "recursos_con_error": 0,
        }

        nave_id = options.get("nave_id")
        if nave_id is not None:
            nave = Nave.objects.filter(id=nave_id).select_related("naviera").first()
            if nave is None:
                self.stdout.write(self.style.ERROR(f"Nave con id={nave_id} no encontrada."))
                return
            naves = [nave]
            self.stdout.write(f"Iniciando sincronización de matriz para nave id={nave_id}...")
        else:
            naves = Nave.objects.filter(is_active=True).select_related("naviera")
            self.stdout.write("Iniciando sincronización de matrices para todas las naves activas...")

        for nave in naves:
            try:
                nave_stats = MotorReglasSITREP.sincronizar_matriz_nave(nave)
                stats["naves_procesadas"] += 1
                stats["recursos_creados"] += nave_stats["recursos_creados"]
                stats["recursos_actualizados"] += nave_stats["recursos_actualizados"]
                stats["recursos_omitidos"] += nave_stats["recursos_omitidos"]
                stats["recursos_con_error"] += nave_stats["recursos_con_error"]
            except Exception as exc:
                logger.error(
                    f"Error processing nave {nave.id} (Naviera: {nave.naviera_id}): {str(exc)}",
                    exc_info=True,
                )
                stats["naves_con_error"] += 1

        self.stdout.write(f"Naves procesadas: {stats['naves_procesadas']}")
        self.stdout.write(f"Recursos creados: {stats['recursos_creados']}")
        self.stdout.write(f"Recursos actualizados: {stats['recursos_actualizados']}")
        self.stdout.write(f"Recursos omitidos: {stats['recursos_omitidos']}")
        self.stdout.write(f"Recursos con error: {stats['recursos_con_error']}")
        self.stdout.write(f"Naves con error: {stats['naves_con_error']}")

        if stats["naves_con_error"] > 0 or stats["recursos_con_error"] > 0:
            self.stdout.write(self.style.WARNING("Sincronización completada con ERRORES parciales. Revise los logs."))
        else:
            self.stdout.write(self.style.SUCCESS("Sincronización de matriz completada."))
