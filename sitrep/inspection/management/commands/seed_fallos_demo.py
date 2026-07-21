import random

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


_OBSERVACIONES_ITEM = [
    "No cumple con el estándar mínimo requerido.",
    "Se detectó desgaste visible que compromete su uso.",
    "Falta certificación o registro vigente.",
    "Fuera de especificación técnica.",
    "Requiere mantención o reemplazo inmediato.",
    "Presenta daño estructural evidente.",
]

_OBSERVACIONES_GENERAL = [
    "Se recomienda atención prioritaria en la próxima escala.",
    "Reportado a mantención, pendiente de repuesto.",
    "",
    "",
]


class Command(BaseCommand):
    """
    Siembra fallos/resoluciones ficticios sobre datos ya sembrados con
    seed_dev_data, para poder probar localmente Fallos activos/nuevos/
    resueltos y el feed sin esperar inspecciones reales.

    Uso:
        python manage.py seed_fallos_demo                  # todas las navieras
        python manage.py seed_fallos_demo --naviera nav-sur

    Idempotente: usa una semilla fija, así que correrlo varias veces
    reproduce el mismo set de filas en vez de acumular más cada vez.
    """
    help = "Siembra fallos/resoluciones ficticios para probar Fallos activos/nuevos/resueltos/feed en local."

    def add_arguments(self, parser):
        parser.add_argument('--naviera', help='Slug de una naviera puntual (default: todas).')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Only executable in local enviroments")

        from sitrep.accounts.models import Naviera

        navieras = Naviera.objects.all()
        if options['naviera']:
            navieras = navieras.filter(slug=options['naviera'])
            if not navieras.exists():
                raise CommandError(f"No existe una naviera con slug '{options['naviera']}'")

        for naviera in navieras:
            self._seed_naviera(naviera)

        self.stdout.write(self.style.SUCCESS('\nFallos ficticios sembrados.'))

    def _seed_naviera(self, naviera):
        from sitrep.accounts.models import Usuario
        from sitrep.inspection.models import MatrizNaveRecurso, PeriodoRevision

        usuario = Usuario.objects.filter(naviera=naviera, rol='mar').first()
        if not usuario:
            self.stdout.write(self.style.WARNING(f'  {naviera.slug}: sin usuario mar, se omite.'))
            return

        rows = list(
            MatrizNaveRecurso.objects.filter(
                nave__naviera=naviera, nave__is_active=True, es_visible=True,
            ).select_related('nave', 'recurso__periodicidad')
        )
        rng = random.Random(42)
        rng.shuffle(rows)

        nuevos = rows[0:6]
        resueltos = rows[6:11]
        antiguos = rows[11:15]

        ahora = timezone.now()
        for mnr in nuevos:
            self._marcar_fallo(mnr, usuario, es_nuevo=True, evento_en=ahora - timezone.timedelta(
                hours=rng.randint(2, 60)))
        for mnr in antiguos:
            self._marcar_fallo(mnr, usuario, es_nuevo=False, evento_en=ahora - timezone.timedelta(
                days=rng.randint(5, 10)))
        for mnr in resueltos:
            self._marcar_resuelto(mnr, usuario, evento_en=ahora - timezone.timedelta(
                hours=rng.randint(2, 60)))

        self.stdout.write(
            f'  {naviera.slug}: {len(nuevos)} nuevos, {len(antiguos)} antiguos, {len(resueltos)} resueltos'
        )

    def _periodo_para(self, mnr):
        from sitrep.inspection.models import PeriodoRevision

        return (
            PeriodoRevision.objects.filter(nave=mnr.nave, periodicidad=mnr.recurso.periodicidad)
            .order_by('-fecha_inicio')
            .first()
        )

    def _crear_ficha(self, mnr, usuario, estado_operativo, evento_en):
        from sitrep.inspection.models import FichaRegistro
        from sitrep.inspection.services import MotorFichas

        periodo = self._periodo_para(mnr)
        if not periodo:
            return None

        rng = random.Random(mnr.id)
        definicion = MotorFichas.construir_definicion_checklist(mnr.recurso, mnr.cantidad)
        if not definicion:
            return None

        fallidos_idx = set()
        if not estado_operativo:
            fallidos_idx = set(rng.sample(range(len(definicion)), k=min(2, len(definicion))))

        payload = {}
        for idx, item in enumerate(definicion):
            if idx in fallidos_idx:
                payload[item['key']] = {
                    'cumple': False,
                    'observacion': rng.choice(_OBSERVACIONES_ITEM),
                }
            else:
                payload[item['key']] = {'cumple': True, 'observacion': ''}

        ficha, _ = FichaRegistro.objects.update_or_create(
            periodo=periodo, recurso=mnr.recurso,
            defaults={
                'usuario': usuario,
                'estado_ficha': 'completa',
                'estado_operativo': estado_operativo,
                'observacion_general': rng.choice(_OBSERVACIONES_GENERAL) if not estado_operativo else '',
                'payload_checklist': payload,
                'definicion_checklist': definicion,
                'modificado_por': usuario,
                'modificado_en': evento_en,
            },
        )
        return ficha

    def _marcar_fallo(self, mnr, usuario, es_nuevo, evento_en):
        if not self._crear_ficha(mnr, usuario, estado_operativo=False, evento_en=evento_en):
            return
        mnr.ultimo_estado_operativo = False
        mnr.ultimo_estado_operativo_anterior = True
        mnr.es_fallo_nuevo = es_nuevo
        mnr.ultimo_estado_operativo_en = evento_en
        mnr.save(update_fields=[
            'ultimo_estado_operativo', 'ultimo_estado_operativo_anterior',
            'es_fallo_nuevo', 'ultimo_estado_operativo_en',
        ])

    def _marcar_resuelto(self, mnr, usuario, evento_en):
        if not self._crear_ficha(mnr, usuario, estado_operativo=True, evento_en=evento_en):
            return
        mnr.ultimo_estado_operativo = True
        mnr.ultimo_estado_operativo_anterior = False
        mnr.es_fallo_nuevo = False
        mnr.ultimo_estado_operativo_en = evento_en
        mnr.save(update_fields=[
            'ultimo_estado_operativo', 'ultimo_estado_operativo_anterior',
            'es_fallo_nuevo', 'ultimo_estado_operativo_en',
        ])
