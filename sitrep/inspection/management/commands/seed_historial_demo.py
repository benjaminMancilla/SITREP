import random
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


# 2 naves nuevas por naviera existente, matriculadas a continuación de las actuales.
_NAVES_NUEVAS = [
    ('nav-sur',       'Nave Naviera III', 'MAT-00503', 45.00, 350, 15),
    ('nav-sur',       'Nave Naviera IV',  'MAT-00504', 70.00, 600, 22),
    ('pacific-fleet', 'Nave Pacific III', 'MAT-00603', 55.00, 420, 18),
    ('pacific-fleet', 'Nave Pacific IV',  'MAT-00604', 90.00, 900, 35),
]

_OBSERVACIONES_FALLO = [
    'Presenta desgaste visible, requiere reemplazo.',
    'Fuera de fecha de vencimiento.',
    'No responde a la prueba de activación.',
    'Componente dañado, no operativo.',
    'Falta documentación de respaldo.',
]

_PERIODICIDADES_MOCK_DETALLADO = {'Quincenal', 'Mensual'}
_PROB_FALLA = 0.07
_DIAS_HISTORIAL = 380  # cobertura ~1 año hacia atrás por cadena de periodos


class Command(BaseCommand):
    """
    Agrega naves y simula ~1 año de historial de periodos/fichas para desarrollo local.

    Requiere que seed_dev_data ya haya corrido (navieras, usuarios y catálogo base).
    Reconstruye PeriodoRevision y FichaRegistro para TODAS las naves activas (viejas y
    nuevas) con fechas de inicio escalonadas por nave/periodicidad, para que no todas
    las naves vayan sincronizadas al mismo día.

    Uso:
        python manage.py seed_historial_demo
        python manage.py seed_historial_demo --skip-naves-nuevas  # solo regenera historial
    """
    help = "Siembra naves adicionales + historial de ~1 año de periodos/fichas para testing local."

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-naves-nuevas', action='store_true',
            help='No crea las naves fixture de dev (nav-sur/pacific-fleet), solo regenera el historial de las naves ya existentes.',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Only executable in local enviroments")

        if not options['skip_naves_nuevas']:
            self._crear_naves_nuevas()

        self.stdout.write('  Sincronizando matriz de recursos...')
        call_command('sincronizar_matriz', verbosity=0)

        self.stdout.write('  Regenerando historial de periodos y fichas...')
        self._regenerar_historial()

        self.stdout.write(self.style.SUCCESS('\nHistorial de demo generado.'))

    # ------------------------------------------------------------------ naves

    def _crear_naves_nuevas(self):
        from sitrep.accounts.models import Naviera
        from sitrep.fleet.models import Dispositivo, Nave

        creadas = 0
        for slug, nombre, matricula, eslora, arqueo, cap in _NAVES_NUEVAS:
            naviera = Naviera.objects.get(slug=slug)
            nave, created = Nave.objects.get_or_create(
                naviera=naviera, matricula=matricula,
                defaults={'nombre': nombre, 'eslora': eslora, 'arqueo_bruto': arqueo, 'capacidad_personas': cap},
            )
            if created:
                creadas += 1
                Dispositivo.objects.get_or_create(
                    nave=nave, nombre='Tablet Puente Mando', defaults={'naviera': naviera},
                )
            self._asegurar_tripulacion(nave)
        self.stdout.write(f'  Naves nuevas: {creadas}')

    def _asegurar_tripulacion(self, nave):
        from sitrep.accounts.models import Usuario
        from sitrep.fleet.models import Tripulacion

        if Tripulacion.objects.filter(nave=nave).exists():
            return
        crew = Usuario.objects.filter(naviera=nave.naviera, rol__in=['capitan', 'mar'])
        for u in crew:
            Tripulacion.objects.get_or_create(usuario=u, nave=nave)

    def _usuario_mar_de(self, nave):
        from sitrep.accounts.models import Usuario
        from sitrep.fleet.models import Tripulacion

        trip = Tripulacion.objects.filter(nave=nave, usuario__rol='mar').select_related('usuario').first()
        if trip:
            return trip.usuario
        trip = Tripulacion.objects.filter(nave=nave).select_related('usuario').first()
        if trip:
            return trip.usuario
        return Usuario.objects.filter(naviera=nave.naviera, rol='mar').first()

    # -------------------------------------------------------------- historial

    def _regenerar_historial(self):
        from sitrep.catalog.models import Periodicidad
        from sitrep.fleet.models import Nave
        from sitrep.inspection.models import MatrizNaveRecurso, PeriodoRevision

        PeriodoRevision.objects.all().delete()
        MatrizNaveRecurso.objects.update(
            ultimo_estado_operativo=None, ultimo_estado_operativo_en=None,
            es_fallo_nuevo=False, ultimo_estado_operativo_anterior=None,
        )

        periodicidades = list(Periodicidad.objects.all())
        naves = list(Nave.objects.filter(is_active=True).select_related('naviera'))

        with transaction.atomic():
            for nave in naves:
                self._asegurar_tripulacion(nave)
                mar = self._usuario_mar_de(nave)
                for periodicidad in periodicidades:
                    self._generar_cadena_periodos(nave, periodicidad, mar)

    def _generar_cadena_periodos(self, nave, periodicidad, mar):
        from sitrep.inspection.services import CatalogoResolver

        hoy = timezone.localdate()
        rng = random.Random(f'{nave.id}-{periodicidad.id}')
        dur = periodicidad.duracion_dias
        stagger = rng.randrange(dur)

        fechas_inicio = []
        fi = hoy - timedelta(days=stagger)
        while (hoy - fi).days < _DIAS_HISTORIAL:
            fechas_inicio.append(fi)
            fi = fi - timedelta(days=dur)
        fechas_inicio.reverse()  # más antiguo -> más reciente

        versiones = CatalogoResolver.versiones_vigentes(nave)
        periodos = self._crear_periodos(nave, periodicidad, fechas_inicio, dur, versiones, rng)
        self._poblar_fichas(nave, periodicidad, mar, periodos, rng)

    def _crear_periodos(self, nave, periodicidad, fechas_inicio, dur, versiones, rng):
        from sitrep.inspection.models import PeriodoRevision

        total = len(fechas_inicio)
        periodos = []
        for idx, fecha_inicio in enumerate(fechas_inicio):
            es_actual = idx == total - 1
            estado = 'pendiente' if es_actual else rng.choices(['cumplido', 'vencido'], weights=[7, 3])[0]
            periodos.append(PeriodoRevision.objects.create(
                nave=nave, periodicidad=periodicidad,
                fecha_inicio=fecha_inicio, fecha_termino=fecha_inicio + timedelta(days=dur - 1),
                estado=estado,
                catalogo_version_central=versiones['central'],
                catalogo_version_naviera=versiones['naviera'],
                catalogo_version_nave=versiones['nave'],
            ))
        return periodos

    def _poblar_fichas(self, nave, periodicidad, mar, periodos, rng):
        from sitrep.inspection.models import MatrizNaveRecurso
        from sitrep.inspection.services import MotorPeriodos

        matrices = list(MatrizNaveRecurso.objects.filter(
            nave=nave, es_visible=True, recurso__periodicidad=periodicidad,
        ).select_related('recurso'))
        if not matrices or mar is None:
            return

        total = len(periodos)
        actual = periodos[-1]
        anterior = periodos[-2] if total >= 2 else None
        antiguos = periodos[:-2] if total >= 2 else []

        mock_detallado = periodicidad.nombre in _PERIODICIDADES_MOCK_DETALLADO

        if anterior is not None and mock_detallado:
            self._llenar_periodo(anterior, matrices, mar, rng, detallado=True)
            MotorPeriodos._cerrar_periodo(anterior)

        self._llenar_periodo(actual, matrices, mar, rng, detallado=mock_detallado)
        MotorPeriodos.sincronizar_estado_periodo_abierto(actual)

        # Simula que hace ~1 año también hubo actividad, sin generar el detalle
        # completo de cada periodo histórico (solo una muestra parcial de recursos).
        for periodo in antiguos[:2]:
            muestra = rng.sample(matrices, k=max(1, len(matrices) // 3))
            self._llenar_periodo(periodo, muestra, mar, rng, detallado=False)

    def _llenar_periodo(self, periodo, matrices, mar, rng, detallado):
        from sitrep.inspection.models import FichaRegistro
        from sitrep.inspection.services import MotorFichas

        hoy = timezone.localdate()
        dias_periodo = (periodo.fecha_termino - periodo.fecha_inicio).days
        max_offset = max(min(dias_periodo, (hoy - periodo.fecha_inicio).days), 0)

        for matriz in matrices:
            recurso = matriz.recurso
            if detallado:
                definicion = MotorFichas.construir_definicion_checklist(recurso, matriz.cantidad)
                payload = {}
                fallo = False
                for item in definicion:
                    falla_item = rng.random() < _PROB_FALLA
                    fallo = fallo or falla_item
                    payload[item['key']] = {
                        'cumple': not falla_item,
                        'observacion': rng.choice(_OBSERVACIONES_FALLO) if falla_item else '',
                    }
                estado_operativo = not fallo
                observacion_general = 'Se detectaron observaciones, ver detalle del checklist.' if fallo else ''
            else:
                definicion = None
                payload = {}
                estado_operativo = rng.random() > 0.1
                observacion_general = ''

            ficha = FichaRegistro.objects.create(
                periodo=periodo, recurso=recurso, usuario=mar,
                estado_ficha='completa', estado_operativo=estado_operativo,
                observacion_general=observacion_general,
                payload_checklist=payload, definicion_checklist=definicion,
            )
            MotorFichas._actualizar_estado_matriz(matriz, estado_operativo)

            offset_dias = rng.randint(0, max_offset) if max_offset > 0 else 0
            fecha_dt = timezone.make_aware(datetime.combine(
                periodo.fecha_inicio + timedelta(days=offset_dias), time(hour=rng.randint(7, 18)),
            ))
            FichaRegistro.objects.filter(pk=ficha.pk).update(fecha_revision=fecha_dt)
