from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


_AREAS = [
    ('Salvamento',    'salvamento',    1),
    ('Incendio',      'incendio',      2),
    ('Navegación',    'navegacion',    3),
    ('Máquinas',      'maquinas',      4),
    ('Gobierno',      'gobierno',      5),
    ('Telecom',       'telecom',       6),
    ('Contaminación', 'contaminacion', 7),
    ('Inundación',    'inundacion',    8),
]

_PERIODICIDADES = [
    ('Semanal',     7,   1,  'mar',    'mar'),
    ('Mensual',     30,  3,  'todos',  'todos'),
    ('Trimestral',  90,  5,  'tierra', 'todos'),
    ('Anual',       365, 10, 'todos',  'todos'),
]

_NAVIERAS = [
    ('Naviera Sur S.A.',    '76.123.456-7', 'nav-sur'),
    ('Pacific Fleet Ltda.', '77.654.321-K', 'pacific-fleet'),
]

_RECURSOS = [
    # (area, periodicidad, proposito_cat, [(nombre, codigo, [reqs])])
    ('Salvamento', 'Semanal', 'Seguridad', [
        ('Chaleco Salvavidas',  '1.1-A', ['Revisar costuras', 'Verificar silbato']),
        ('Aro Salvavidas',      '1.2-B', ['Comprobar cuerda', 'Verificar luz de destellos']),
        ('Balsa Inflable',      '1.3-C', ['Fecha de caducidad vigente', 'Precinto intacto']),
        ('Cohete Señalización', '1.4-D', ['Dentro de fecha de vencimiento']),
    ]),
    ('Incendio', 'Mensual', 'Seguridad', [
        ('Extintor CO2',            '2.1-A', ['Presión en zona verde', 'Pin de seguridad presente']),
        ('Manguera Contraincendio', '2.2-B', ['Sin daño en racor', 'Longitud correcta']),
        ('Traje de Bombero',        '2.3-C', ['Sin rasgaduras visibles', 'Cierre operativo']),
        ('Detector de Humo',        '2.4-D', ['Test de alarma OK', 'Batería al día']),
    ]),
    ('Navegación', 'Mensual', 'Operacional', [
        ('Radar ARPA',      '3.1-A', ['Calibración vigente', 'Imagen nítida en pantalla']),
        ('GPS Principal',   '3.2-B', ['Señal mínima 4 satélites', 'Sin alarmas activas']),
        ('Compás Magnético','3.3-C', ['Sin desvíos anormales', 'Iluminación OK']),
    ]),
    ('Máquinas', 'Trimestral', 'Operacional', [
        ('Motor Principal',    '4.1-A', ['Nivel de aceite OK', 'Sin fugas visibles', 'RPM estables']),
        ('Generador Auxiliar', '4.2-B', ['Prueba de arranque OK', 'Nivel combustible >50%']),
        ('Bomba de Sentina',   '4.3-C', ['Cebado correcto', 'Válvula de retención operativa']),
    ]),
    ('Gobierno', 'Trimestral', 'Seguridad', [
        ('Timón de Emergencia', '5.1-A', ['Mecanismo sin holguras', 'Lubricación OK']),
        ('Sistema de Gobierno', '5.2-B', ['Respuesta hidráulica normal', 'Sin fugas']),
    ]),
    ('Telecom', 'Mensual', 'Operacional', [
        ('Radio VHF',   '6.1-A', ['Alcance verificado canal 16', 'Batería >80%']),
        ('EPIRB',       '6.2-B', ['Registro vigente', 'Batería en fecha']),
        ('SART Radar',  '6.3-C', ['Test de activación OK']),
    ]),
]


class Command(BaseCommand):
    """
    Siembra datos de desarrollo variados en todos los modelos.

    Uso:
        python manage.py seed_dev_data            # idempotente, agrega si no existe
        python manage.py seed_dev_data --flush    # borra todo y vuelve a sembrar

    Credenciales creadas:
        admin / admin                  : admin_sitrep (superuser)
        nav-sur-admin / 1234           : admin_naviera de Naviera Sur
        nav-sur-capitan / 1234         : capitan de Naviera Sur
        nav-sur-tierra / 1234          : tierra de Naviera Sur
        nav-sur-mar1, nav-sur-mar2 / 1234
        pacific-fleet-admin / 1234     : ídem para Pacific Fleet
        … (misma convención)
    """
    help = "Siembra datos de desarrollo en todos los modelos para testing local."

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush', action='store_true',
            help='Elimina datos existentes antes de sembrar (hard delete).',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Only executable in local enviroments")
        if options['flush']:
            self._flush()
        self._seed_catalog()
        navieras = self._seed_navieras()
        self._seed_naves_y_usuarios(navieras)
        self.stdout.write('  Sincronizando matriz de recursos...')
        call_command('sincronizar_matriz', verbosity=0)
        self.stdout.write('  Sincronizando períodos de revisión...')
        call_command('sincronizar_periodos', verbosity=0)
        self._seed_fichas()
        self.stdout.write(self.style.SUCCESS(
            '\nSeed completado.\n'
            '  admin / admin              → superuser\n'
            '  nav-sur-capitan / 1234     → capitán Naviera Sur\n'
            '  nav-sur-mar1 / 1234        → tripulación Naviera Sur\n'
            '  pacific-fleet-capitan / 1234\n'
        ))


    def _flush(self):
        from sitrep.accounts.models import Naviera, Usuario
        from sitrep.fleet.models import Dispositivo, Nave, Tripulacion
        from sitrep.inspection.models import FichaRegistro, MatrizNaveRecurso, PeriodoRevision

        FichaRegistro.objects.all().delete()
        PeriodoRevision.objects.all().delete()
        MatrizNaveRecurso.objects.all().delete()
        Tripulacion.objects.all().delete()
        Dispositivo.objects.all().delete()
        Nave.objects.all().delete()
        Usuario.objects.all().delete()
        Naviera.objects.all().delete()
        self.stdout.write(self.style.WARNING('  Datos previos eliminados.'))


    def _seed_catalog(self):
        from sitrep.catalog.models import Area, Periodicidad, Proposito

        for nombre, token, orden in _AREAS:
            Area.objects.get_or_create(
                nombre=nombre,
                defaults={'token_color': token, 'orden': orden, 'nombre_tecnico': nombre.lower()},
            )

        for nombre, dias, offset, resp, vis in _PERIODICIDADES:
            Periodicidad.objects.get_or_create(
                nombre=nombre,
                defaults={
                    'duracion_dias': dias, 'offset_dias': offset,
                    'responsabilidad': resp, 'visibilidad': vis,
                },
            )

        for cat in ('Seguridad', 'Operacional'):
            for tipo in ('Material', 'Documentacion'):
                Proposito.objects.get_or_create(
                    categoria=cat, tipo=tipo,
                    defaults={'nombre': f'{tipo} de {cat}'},
                )

        self._seed_recursos()
        self.stdout.write('  Catálogo OK')

    def _seed_recursos(self):
        from sitrep.catalog.models import Area, Periodicidad, Proposito, Recurso

        periodicidades = {p.nombre: p for p in Periodicidad.objects.all()}
        areas = {a.nombre: a for a in Area.objects.all()}

        for area_nombre, period_nombre, prop_cat, recursos in _RECURSOS:
            area = areas[area_nombre]
            period = periodicidades[period_nombre]
            prop = Proposito.objects.get(categoria=prop_cat, tipo='Material')
            for nombre, codigo, reqs in recursos:
                Recurso.objects.get_or_create(
                    nombre=nombre, periodicidad=period, area=area, naviera=None,
                    defaults={'codigo': codigo, 'proposito': prop, 'requerimientos': reqs},
                )


    def _seed_navieras(self):
        from sitrep.accounts.models import Naviera

        result = []
        for nombre, rut, slug in _NAVIERAS:
            nav, _ = Naviera.objects.get_or_create(rut=rut, defaults={'nombre': nombre, 'slug': slug})
            result.append(nav)
        self.stdout.write(f'  Navieras: {len(result)}')
        return result


    def _seed_naves_y_usuarios(self, navieras):
        from sitrep.accounts.models import Usuario
        from sitrep.fleet.models import Dispositivo, Nave, Tripulacion

        if not Usuario.objects.filter(username='admin').exists():
            u = Usuario(username='admin', rut='10000000-0', rol='admin_sitrep', is_superuser=True, is_staff=True, email='admin@dev.local')
            u.set_password('admin')
            u.save()
            self.stdout.write('  Superuser admin/admin creado')

        for idx, nav in enumerate(navieras):
            slug = nav.slug
            base_rut = (idx + 2) * 10_000_000

            role_defs = [
                ('admin_naviera', f'{slug}-admin',   f'{base_rut + 1}-0'),
                ('capitan',       f'{slug}-capitan', f'{base_rut + 2}-0'),
                ('tierra',        f'{slug}-tierra',  f'{base_rut + 3}-0'),
                ('mar',           f'{slug}-mar1',    f'{base_rut + 4}-0'),
                ('mar',           f'{slug}-mar2',    f'{base_rut + 5}-0'),
            ]

            users_by_role: dict[str, list] = {}
            for rol, username, rut in role_defs:
                u, created = Usuario.objects.get_or_create(
                    username=username,
                    defaults={
                        'rut': rut, 'naviera': nav, 'rol': rol,
                        'password': make_password('1234'),
                        'email': f'{username}@dev.local',
                        'first_name': username.split('-')[-1].capitalize(),
                        'last_name': nav.nombre.split()[0],
                        'is_active': True,
                    },
                )
                if created and rol in ('mar', 'capitan'):
                    u.set_pin('1234')
                    u.save(update_fields=['pin_kiosco'])
                users_by_role.setdefault(rol, []).append(u)

            capitan_list = users_by_role.get('capitan', [])
            mar_list = users_by_role.get('mar', [])
            crew = capitan_list + mar_list

            naves_config = [
                (f'Nave {nav.nombre.split()[0]} I',  f'MAT-{nav.id:03d}01', 85.50, 800, 30),
                (f'Nave {nav.nombre.split()[0]} II', f'MAT-{nav.id:03d}02', 62.00, 500, 20),
            ]
            for nombre_nave, matricula, eslora, arqueo, cap in naves_config:
                nave, _ = Nave.objects.get_or_create(
                    naviera=nav, matricula=matricula,
                    defaults={
                        'nombre': nombre_nave, 'eslora': eslora,
                        'arqueo_bruto': arqueo, 'capacidad_personas': cap,
                    },
                )
                for u in crew:
                    Tripulacion.objects.get_or_create(usuario=u, nave=nave)
                Dispositivo.objects.get_or_create(
                    nave=nave, nombre='Tablet Puente Mando',
                    defaults={'naviera': nav},
                )

        self.stdout.write('  Usuarios, naves y tripulación OK')


    def _seed_fichas(self):
        from sitrep.accounts.models import Usuario
        from sitrep.inspection.models import FichaRegistro, MatrizNaveRecurso, PeriodoRevision

        mar = Usuario.objects.filter(rol='mar').first()
        if not mar:
            return

        estados_periodo = ['pendiente', 'en_proceso', 'cumplido', 'vencido', 'cumplido', 'en_proceso']
        configs_ficha = [
            ('completa',    True,  ''),
            ('completa',    False, 'Elemento no cumple especificación técnica.'),
            ('en_progreso', None,  'Revisión en curso.'),
        ]

        for i, periodo in enumerate(PeriodoRevision.objects.select_related('nave')[:10]):
            periodo.estado = estados_periodo[i % len(estados_periodo)]
            periodo.save(update_fields=['estado'])

            mnrs = list(MatrizNaveRecurso.objects.filter(nave=periodo.nave).select_related('recurso')[:3])
            for j, mnr in enumerate(mnrs):
                estado_ficha, estado_op, obs = configs_ficha[j % len(configs_ficha)]
                FichaRegistro.objects.get_or_create(
                    periodo=periodo, recurso=mnr.recurso,
                    defaults={
                        'usuario': mar,
                        'estado_ficha': estado_ficha,
                        'estado_operativo': estado_op,
                        'observacion_general': obs,
                        'payload_checklist': {},
                    },
                )

        self.stdout.write('  Fichas de registro OK')
