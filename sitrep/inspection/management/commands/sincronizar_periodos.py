from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db import OperationalError
from django.utils import timezone
import time

from sitrep.inspection.models import PeriodoRevision
from sitrep.inspection.services import MotorPeriodos

class Command(BaseCommand):
    help = "Sincroniza periodos de revision para todas las naves activas."

    def add_arguments(self, parser):
        parser.add_argument(
            '--forzar-nave', type=int, default=None,
            help='Dev only: vence ahora el periodo abierto de esta nave (por id) antes de sincronizar.',
        )
        parser.add_argument(
            '--forzar-todas', action='store_true',
            help='Dev only: vence ahora el periodo abierto de TODAS las naves antes de sincronizar.',
        )

    def _forzar_vencimiento(self, *, nave_id):
        if not settings.DEBUG:
            raise CommandError("--forzar-nave/--forzar-todas solo son ejecutables en entornos locales")
        abiertos = PeriodoRevision.objects.filter(estado__in=PeriodoRevision.ESTADOS_ABIERTOS).select_related('periodicidad')
        if nave_id is not None:
            abiertos = abiertos.filter(nave_id=nave_id)
        hoy = timezone.localdate()
        forzados = 0
        for periodo in abiertos:
            periodo.fecha_termino = hoy - timedelta(days=periodo.periodicidad.offset_dias + 1)
            periodo.save(update_fields=['fecha_termino'])
            forzados += 1
        self.stdout.write(f"Periodos forzados a vencimiento: {forzados}")

    def handle(self, *args, **options):
        if options['forzar_todas']:
            self._forzar_vencimiento(nave_id=None)
        elif options['forzar_nave'] is not None:
            self._forzar_vencimiento(nave_id=options['forzar_nave'])

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
