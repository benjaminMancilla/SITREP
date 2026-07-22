from datetime import date, datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from sitrep.accounts.models import Naviera, Usuario
from sitrep.fleet.models import Nave, Tripulacion
from sitrep.catalog.models import Area, Periodicidad, Recurso, CatalogoVersion
from sitrep.catalog.services import requerimientos_estandar, CatalogoEditorService, CatalogoResolver
from .models import (
    FichaRegistro,
    MatrizNaveRecurso,
    PeriodoRevision,
)
from sitrep.fleet.tests import TenantFixturesMixin
from .presenters import construir_hitos_inminentes
from .services import MotorFichas, MotorPeriodos, MotorReglasSITREP, TenantQueryService


class TestMotorReglasSITREP(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Motor",
            rut="33333333-3",
            slug="naviera-motor",
        )
        self.nave = Nave.objects.create(
            naviera=self.naviera,
            nombre="Nave Motor",
            matricula="NVM-001",
            eslora=25.0,
            arqueo_bruto=300,
            capacidad_personas=20,
        )
        self.periodicidad = Periodicidad.objects.create(
            nombre="Semanal",
            duracion_dias=7,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )
        self.catalogo_version = CatalogoVersion.crear_para_scope()
        self.regla_semanal = {
            "atributo": "eslora",
            "condiciones": [
                {
                    "operador": "<=",
                    "valor": 10,
                    "resultado_cantidad": 0,
                    "resultado_visible": False,
                },
                {
                    "operador": "<=",
                    "valor": 50,
                    "resultado_cantidad": 2,
                    "resultado_visible": True,
                },
                {
                    "operador": ">",
                    "valor": 50,
                    "resultado_cantidad": 4,
                    "resultado_visible": True,
                },
            ],
            "fallback_cantidad": 0,
            "fallback_visible": False,
        }

    def _crear_recurso(self, nombre, regla_aplicacion):
        return Recurso.objects.create(
            categoria="Seguridad",
            tipo="Material",
            periodicidad=self.periodicidad,
            nombre=nombre,
            requerimientos=[],
            regla_aplicacion=regla_aplicacion,
            catalogo_version=self.catalogo_version,
        )

    def test_sincronizar_matriz_nave_crea_entradas(self):
        """Al sincronizar una nave con recursos del catálogo, crea MatrizNaveRecurso"""
        recurso = self._crear_recurso(
            nombre="Extintor",
            regla_aplicacion=self.regla_semanal,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz = MatrizNaveRecurso.objects.get(nave=self.nave, recurso=recurso)
        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_sincronizar_matriz_nave_siempre_recalcula_valores_previos(self):
        """El motor de reglas es la única fuente de verdad: cualquier valor previo
        en la matriz (manual o desactualizado) se sobreescribe al sincronizar."""
        recurso = self._crear_recurso(
            nombre="Chaleco",
            regla_aplicacion=self.regla_semanal,
        )
        matriz = MatrizNaveRecurso.objects.create(
            nave=self.nave,
            recurso=recurso,
            cantidad=99,
            es_visible=False,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz.refresh_from_db()
        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_sincronizar_matriz_nave_actualiza_entradas_existentes(self):
        recurso = self._crear_recurso(
            nombre="Botiquin",
            regla_aplicacion=self.regla_semanal,
        )
        matriz = MatrizNaveRecurso.objects.create(
            nave=self.nave,
            recurso=recurso,
            cantidad=1,
            es_visible=False,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz.refresh_from_db()
        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_sincronizar_matriz_nave_incluye_todo_el_catalogo(self):
        """Todo recurso del catálogo aplica a toda nave — catálogo único, sin excepciones por naviera."""
        recurso_a = self._crear_recurso(
            nombre="Recurso A",
            regla_aplicacion=self.regla_semanal,
        )
        recurso_b = self._crear_recurso(
            nombre="Recurso B",
            regla_aplicacion=self.regla_semanal,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        recursos_en_matriz = set(
            MatrizNaveRecurso.objects.filter(nave=self.nave).values_list(
                "recurso_id",
                flat=True,
            )
        )
        self.assertEqual(recursos_en_matriz, {recurso_a.id, recurso_b.id})

    def test_sincronizar_matriz_nave_retorna_estadisticas(self):
        """Retorna estadisticas de creados, actualizados y errores"""
        recurso_creado = self._crear_recurso(
            nombre="Recurso Creado",
            regla_aplicacion=self.regla_semanal,
        )
        recurso_actualizado = self._crear_recurso(
            nombre="Recurso Actualizado",
            regla_aplicacion=self.regla_semanal,
        )

        MatrizNaveRecurso.objects.create(
            nave=self.nave,
            recurso=recurso_actualizado,
            cantidad=1,
            es_visible=False,
        )

        stats = MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        self.assertEqual(
            stats,
            {
                "recursos_creados": 1,
                "recursos_actualizados": 1,
                "recursos_omitidos": 0,
                "recursos_con_error": 0,
            },
        )
        self.assertTrue(
            MatrizNaveRecurso.objects.filter(nave=self.nave, recurso=recurso_creado).exists()
        )

    def test_sincronizar_matriz_nave_continua_si_un_recurso_falla(self):
        """Si un recurso falla, los demás recursos deben seguir procesándose"""
        recurso_ok = self._crear_recurso(
            nombre="Recurso OK",
            regla_aplicacion=self.regla_semanal,
        )
        recurso_falla = self._crear_recurso(
            nombre="Recurso Falla",
            regla_aplicacion=self.regla_semanal,
        )

        original_create = MatrizNaveRecurso.objects.create

        def create_con_fallo(*args, **kwargs):
            if kwargs.get("recurso") == recurso_falla:
                raise RuntimeError("fallo simulado de recurso")
            return original_create(*args, **kwargs)

        with patch.object(
            MatrizNaveRecurso.objects,
            "create",
            side_effect=create_con_fallo,
        ):
            with self.assertLogs("sitrep.inspection.services", level="ERROR") as logs:
                stats = MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        self.assertEqual(stats["recursos_con_error"], 1)
        self.assertEqual(stats["recursos_creados"], 1)
        self.assertEqual(stats["recursos_actualizados"], 0)
        self.assertEqual(stats["recursos_omitidos"], 0)
        self.assertTrue(
            MatrizNaveRecurso.objects.filter(nave=self.nave, recurso=recurso_ok).exists()
        )
        self.assertFalse(
            MatrizNaveRecurso.objects.filter(nave=self.nave, recurso=recurso_falla).exists()
        )
        self.assertTrue(any("Error processing recurso" in linea for linea in logs.output))


class TestSincronizarMatrizNaveVersionado(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(nombre="Naviera S", rut="66666666-6", slug="naviera-s")
        self.nave = Nave.objects.create(
            naviera=self.naviera, nombre="Nave S", matricula="NVS-001",
            eslora=25.0, arqueo_bruto=300, capacidad_personas=20,
        )
        self.periodicidad = Periodicidad.objects.create(nombre="Semanal", duracion_dias=7, offset_dias=1, responsabilidad="mar", visibilidad="todos")

    def test_pk_drift_actualiza_recurso_fk_preserva_historial_operativo(self):
        _, (r1,) = CatalogoEditorService.publicar(filas=[{
            'base': None,
            'cambios': {
                'categoria': 'Seguridad', 'tipo': 'Material', 'periodicidad_id': self.periodicidad.id,
                'nombre': 'Extintor', 'requerimientos': [], 'regla_aplicacion': None,
            },
        }])
        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)
        matriz = MatrizNaveRecurso.objects.get(nave=self.nave, recurso=r1)
        matriz_pk = matriz.pk
        matriz.ultimo_estado_operativo = True
        matriz.save(update_fields=['ultimo_estado_operativo'])

        _, (r2,) = CatalogoEditorService.publicar(filas=[{'base': r1, 'cambios': {'nombre': 'Extintor v2'}}])
        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz.refresh_from_db()
        self.assertEqual(matriz.pk, matriz_pk)  # misma fila, no recreada
        self.assertEqual(matriz.recurso_id, r2.id)  # apunta al PK nuevo
        self.assertTrue(matriz.ultimo_estado_operativo)  # historial preservado

    def test_lineage_removida_oculta_matriz_sin_borrarla(self):
        _, (r1,) = CatalogoEditorService.publicar(filas=[{
            'base': None,
            'cambios': {
                'categoria': 'Seguridad', 'tipo': 'Material', 'periodicidad_id': self.periodicidad.id,
                'nombre': 'Extintor', 'requerimientos': [], 'regla_aplicacion': None,
            },
        }])
        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)
        CatalogoEditorService.publicar(filas=[{'base': r1, 'cambios': {'activo': False}}])
        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz = MatrizNaveRecurso.objects.get(nave=self.nave, recurso=r1)
        self.assertFalse(matriz.es_visible)

    def test_catalogo_independiente_oculta_matrices_centrales(self):
        _, (r1,) = CatalogoEditorService.publicar(filas=[{
            'base': None,
            'cambios': {
                'categoria': 'Seguridad', 'tipo': 'Material', 'periodicidad_id': self.periodicidad.id,
                'nombre': 'Extintor', 'requerimientos': [], 'regla_aplicacion': None,
            },
        }])
        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)
        self.nave.catalogo_independiente = True
        self.nave.save(update_fields=['catalogo_independiente'])
        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz = MatrizNaveRecurso.objects.get(nave=self.nave, recurso=r1)
        self.assertFalse(matriz.es_visible)


class TestMotorPeriodosEstados(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Estados",
            rut="55555555-5",
            slug="naviera-estados",
        )
        self.periodicidad = Periodicidad.objects.create(
            nombre="Mensual",
            duracion_dias=30,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )
        self.catalogo_version = CatalogoVersion.crear_para_scope()
        self.recurso_a = Recurso.objects.create(
            categoria="Seguridad", tipo="Material",
            periodicidad=self.periodicidad,
            nombre="Extintor A",
            requerimientos=requerimientos_estandar("vigencia", "presion"),
            regla_aplicacion=None,
            catalogo_version=self.catalogo_version,
        )
        self.recurso_b = Recurso.objects.create(
            categoria="Seguridad", tipo="Material",
            periodicidad=self.periodicidad,
            nombre="Extintor B",
            requerimientos=requerimientos_estandar("sello"),
            regla_aplicacion=None,
            catalogo_version=self.catalogo_version,
        )
        self.recurso_sin_checklist = Recurso.objects.create(
            categoria="Seguridad", tipo="Material",
            periodicidad=self.periodicidad,
            nombre="Radio VHF",
            requerimientos=[],
            regla_aplicacion=None,
            catalogo_version=self.catalogo_version,
        )
        self.usuario = Usuario.objects.create_user(
            username="marinero_estados",
            password="password-seguro-123",
            naviera=self.naviera,
            rut="55555555-6",
            email="marinero@example.com",
            rol="mar",
        )
        self.nave = Nave.objects.create(
            naviera=self.naviera,
            nombre="Nave Estados",
            matricula="NVE-001",
            eslora=20.0,
            arqueo_bruto=200,
            capacidad_personas=12,
        )
        self.periodo = PeriodoRevision.objects.get(
            nave=self.nave,
            periodicidad=self.periodicidad,
        )

    def _crear_ficha(self, recurso, estado_operativo, payload_checklist, observacion_general=""):
        return MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=estado_operativo,
            observacion_general=observacion_general,
            payload_checklist=payload_checklist,
        )

    def test_get_periodos_abiertos_de_nave_incluye_pendiente_y_en_proceso(self):
        otra_periodicidad = Periodicidad.objects.create(
            nombre="Semanal Estados",
            duracion_dias=7,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )
        periodo_en_proceso = PeriodoRevision.objects.create(
            nave=self.nave,
            periodicidad=otra_periodicidad,
            fecha_inicio=timezone.localdate(),
            fecha_termino=timezone.localdate(),
            estado="en_proceso",
        )
        PeriodoRevision.objects.create(
            nave=self.nave,
            periodicidad=otra_periodicidad,
            fecha_inicio=timezone.localdate(),
            fecha_termino=timezone.localdate(),
            estado="cumplido",
        )

        periodos_ids = set(
            TenantQueryService.get_periodos_abiertos_de_nave(self.nave).values_list("id", flat=True)
        )

        self.assertIn(self.periodo.id, periodos_ids)
        self.assertIn(periodo_en_proceso.id, periodos_ids)
        self.assertEqual(len(periodos_ids), 2)

    def test_crear_ficha_parcial_mantiene_periodo_pendiente(self):
        ficha = self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=None,
            payload_checklist={"vigencia": {"cumple": True}},
        )

        self.periodo.refresh_from_db()

        self.assertIsNone(ficha.estado_operativo)
        self.assertEqual(self.periodo.estado, "pendiente")

    def test_crear_ficha_completa_cambia_periodo_a_en_proceso(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=True,
            payload_checklist={
                "vigencia": {"cumple": True},
                "presion": {"cumple": True},
            },
        )

        self.periodo.refresh_from_db()

        self.assertEqual(self.periodo.estado, "en_proceso")

    def test_periodo_sin_registros_termina_vencido(self):
        self.assertEqual(MotorPeriodos._determinar_estado_cierre(self.periodo), "vencido")

    def test_periodo_con_registro_incompleto_termina_vencido(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=None,
            payload_checklist={"vigencia": {"cumple": True}},
        )

        self.assertEqual(MotorPeriodos._determinar_estado_cierre(self.periodo), "vencido")

    def test_periodo_completo_y_operativo_termina_conforme(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=True,
            payload_checklist={
                "vigencia": {"cumple": True},
                "presion": {"cumple": True},
            },
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_b,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={"sello": {"cumple": True}},
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_sin_checklist,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={},
        )

        self.assertEqual(MotorPeriodos._determinar_estado_cierre(self.periodo), "cumplido")

    def test_periodo_completo_con_observacion_termina_cumplido(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=True,
            payload_checklist={
                "vigencia": {"cumple": True},
                "presion": {"cumple": True},
            },
            observacion_general="Requiere seguimiento",
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_b,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={"sello": {"cumple": True}},
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_sin_checklist,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={},
        )

        self.assertEqual(MotorPeriodos._determinar_estado_cierre(self.periodo), "cumplido")

    def test_periodo_completo_con_falla_termina_cumplido(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=False,
            payload_checklist={
                "vigencia": {"cumple": True},
                "presion": {"cumple": False},
            },
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_b,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={"sello": {"cumple": True}},
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_sin_checklist,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={},
        )

        self.assertEqual(MotorPeriodos._determinar_estado_cierre(self.periodo), "cumplido")

    def test_estado_abierto_sin_fichas_completas_permanece_pendiente(self):
        self.assertEqual(
            MotorPeriodos._calcular_estado_abierto(self.nave, self.periodo),
            "pendiente",
        )

    def test_estado_abierto_con_una_ficha_completa_pasa_a_en_proceso(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=True,
            payload_checklist={
                "vigencia": {"cumple": True},
                "presion": {"cumple": True},
            },
        )

        self.assertEqual(
            MotorPeriodos._calcular_estado_abierto(self.nave, self.periodo),
            "en_proceso",
        )

    def test_ficha_con_requerimientos_exige_campo_cumple_en_cada_item(self):
        ficha = FichaRegistro.objects.create(
            periodo=self.periodo,
            recurso=self.recurso_a,
            usuario=self.usuario,
            estado_operativo=True,
            payload_checklist={"vigencia": True, "presion": True},
        )

        self.assertFalse(MotorPeriodos._es_ficha_completa(ficha))

    def test_ficha_sin_requerimientos_es_completa_si_tiene_estado_operativo(self):
        ficha = FichaRegistro.objects.create(
            periodo=self.periodo,
            recurso=self.recurso_sin_checklist,
            usuario=self.usuario,
            estado_operativo=False,
            payload_checklist={},
        )

        self.assertTrue(MotorPeriodos._es_ficha_completa(ficha))

    def test_sincronizar_periodos_nave_retorna_conteo_de_errores(self):
        periodicidad_extra = Periodicidad.objects.create(
            nombre="Diaria Estados",
            duracion_dias=1,
            offset_dias=0,
            responsabilidad="mar",
            visibilidad="todos",
        )

        original_crear_periodo_abierto = MotorPeriodos._crear_periodo_abierto

        def crear_periodo_con_fallo(nave, periodicidad, fecha_inicio):
            if periodicidad == periodicidad_extra:
                raise RuntimeError("fallo simulado de periodicidad")
            return original_crear_periodo_abierto(nave, periodicidad, fecha_inicio)

        with patch.object(
            MotorPeriodos,
            "_crear_periodo_abierto",
            side_effect=crear_periodo_con_fallo,
        ):
            with self.assertLogs("sitrep.inspection.services", level="ERROR") as logs:
                stats = MotorPeriodos.sincronizar_periodos_nave(self.nave)

        self.assertEqual(stats["periodos_con_error"], 1)
        self.assertTrue(any("Error processing periodicidad" in linea for linea in logs.output))
        self.assertIn("periodos_creados", stats)
        self.assertIn("periodos_vencidos", stats)

    def test_sincronizar_periodos_nave_no_resincroniza_matriz_si_nada_vence(self):
        """Un tick del cron sin ningún período vencido no debe tocar la matriz."""
        with patch.object(MotorReglasSITREP, "sincronizar_matriz_nave") as mock_sync:
            MotorPeriodos.sincronizar_periodos_nave(self.nave)

        mock_sync.assert_not_called()

    def test_sincronizar_periodos_nave_resincroniza_matriz_al_crear_periodo_nuevo(self):
        """Una periodicidad sin período abierto todavía sí cuenta como cambio de período."""
        Periodicidad.objects.create(
            nombre="Trimestral Estados",
            duracion_dias=90,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )

        with patch.object(MotorReglasSITREP, "sincronizar_matriz_nave") as mock_sync:
            MotorPeriodos.sincronizar_periodos_nave(self.nave)

        mock_sync.assert_called_once_with(self.nave)

    def test_sincronizar_periodos_nave_resincroniza_matriz_al_vencer_periodo(self):
        self.periodo.fecha_termino = timezone.localdate() - timedelta(days=5)
        self.periodo.save(update_fields=["fecha_termino"])

        with patch.object(MotorReglasSITREP, "sincronizar_matriz_nave") as mock_sync:
            MotorPeriodos.sincronizar_periodos_nave(self.nave)

        mock_sync.assert_called_once_with(self.nave)


class TestIntegracionMotorReglas(TestCase):
    REGLA_POR_ESLORA = {
        "atributo": "eslora",
        "condiciones": [
            {
                "operador": "<=",
                "valor": 10,
                "resultado_cantidad": 0,
                "resultado_visible": False,
            },
            {
                "operador": "<=",
                "valor": 30,
                "resultado_cantidad": 2,
                "resultado_visible": True,
            },
            {
                "operador": ">",
                "valor": 30,
                "resultado_cantidad": 4,
                "resultado_visible": True,
            },
        ],
        "fallback_cantidad": 0,
        "fallback_visible": False,
    }

    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Integración",
            rut="99999999-9",
            slug="naviera-integracion",
        )
        self.periodicidad = Periodicidad.objects.create(
            nombre="Semanal Integración",
            duracion_dias=7,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )
        self.usuario = Usuario.objects.create_user(
            username="marinero_integracion",
            password="password-seguro-123",
            naviera=self.naviera,
            rut="99999999-9",
            email="marinero_integracion@example.com",
            rol="mar",
        )
        self.catalogo_version = CatalogoVersion.crear_para_scope()

    def _crear_nave(self, nombre, matricula, eslora, naviera=None):
        return Nave.objects.create(
            naviera=naviera or self.naviera,
            nombre=nombre,
            matricula=matricula,
            eslora=eslora,
            arqueo_bruto=200,
            capacidad_personas=12,
        )

    def _crear_recurso(
        self,
        nombre,
        regla_aplicacion,
        requerimientos=None,
        periodicidad=None,
        codigo=None,
        area=None,
    ):
        requerimientos_tipados = requerimientos_estandar(*(requerimientos or []))
        if regla_aplicacion:
            # Mismo criterio que la migración de datos: un recurso con motor de
            # reglas asignado declara el requerimiento "cantidad" en su catálogo.
            requerimientos_tipados.append(
                {"id": MotorFichas.CANTIDAD_REQUISITO_KEY, "tipo": "cantidad"}
            )
        return Recurso.objects.create(
            categoria="Seguridad", tipo="Material",
            periodicidad=periodicidad or self.periodicidad,
            area=area,
            nombre=nombre,
            codigo=codigo,
            requerimientos=requerimientos_tipados,
            regla_aplicacion=regla_aplicacion,
            catalogo_version=self.catalogo_version,
        )

    def _get_matriz(self, nave, recurso):
        return MatrizNaveRecurso.objects.get(nave=nave, recurso=recurso)

    def _get_periodo(self, nave):
        return PeriodoRevision.objects.get(nave=nave, periodicidad=self.periodicidad)

    def _payload_con_cantidad(self, cantidad, **items):
        payload = dict(items)
        payload[MotorFichas.CANTIDAD_REQUISITO_KEY] = {
            "cumple": cantidad,
            "observacion": "",
        }
        return payload

    def test_nave_pequena_obtiene_cantidad_correcta_segun_eslora(self):
        """Nave con eslora=8 (<=10) debe tener cantidad=0 y es_visible=False"""
        recurso = self._crear_recurso(
            nombre="Extintor Integración Pequeña",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )
        nave = self._crear_nave("Lancha Integración", "INT-001", 8)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 0)
        self.assertFalse(matriz.es_visible)

    def test_nave_mediana_obtiene_cantidad_correcta_segun_eslora(self):
        """Nave con eslora=20 (<=30) debe tener cantidad=2 y es_visible=True"""
        recurso = self._crear_recurso(
            nombre="Extintor Integración Mediana",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )
        nave = self._crear_nave("Patrullera Integración", "INT-002", 20)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_nave_grande_obtiene_cantidad_correcta_segun_eslora(self):
        """Nave con eslora=50 (>30) debe tener cantidad=4 y es_visible=True"""
        recurso = self._crear_recurso(
            nombre="Extintor Integración Grande",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )
        nave = self._crear_nave("Buque Integración", "INT-003", 50)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 4)
        self.assertTrue(matriz.es_visible)

    def test_signal_post_save_nave_sincroniza_matriz_automaticamente(self):
        """Al crear una nave, el Signal dispara sincronización y MatrizNaveRecurso existe"""
        recurso = self._crear_recurso(
            nombre="Recurso Signal",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )

        nave = self._crear_nave("Nave Signal", "INT-004", 20)

        matriz = self._get_matriz(nave, recurso)
        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_editar_nave_no_resincroniza_matriz_automaticamente(self):
        """Editar una nave existente (ej. desde admin) NO debe resincronizar su
        matriz: eso rompería la inmutabilidad de fichas ya abiertas. La sync
        solo ocurre en cambio de período o de forma explícita."""
        recurso = self._crear_recurso(
            nombre="Recurso Actualizable",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )
        nave = self._crear_nave("Nave Editable", "INT-005", 20)

        matriz = self._get_matriz(nave, recurso)
        self.assertEqual(matriz.cantidad, 2)

        nave.eslora = 50
        nave.save()

        matriz.refresh_from_db()
        self.assertEqual(matriz.cantidad, 2)

    def test_recurso_sin_regla_usa_fallback_default(self):
        """Recurso con regla_aplicacion=None usa fallback (0, True)"""
        recurso = self._crear_recurso(
            nombre="Recurso Sin Regla",
            regla_aplicacion=None,
        )
        nave = self._crear_nave("Nave Fallback", "INT-006", 20)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 0)
        self.assertTrue(matriz.es_visible)

    def test_recurso_del_catalogo_aplica_a_todas_las_naves(self):
        """Catálogo único: un recurso aplica a la matriz de toda nave, sin excepción por naviera."""
        recurso = self._crear_recurso(
            nombre="Recurso Integración",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )
        nave_a = self._crear_nave("Nave Global A", "INT-007", 20)
        nave_b = self._crear_nave("Nave Global B", "INT-008", 50)

        self.assertTrue(MatrizNaveRecurso.objects.filter(nave=nave_a, recurso=recurso).exists())
        self.assertTrue(MatrizNaveRecurso.objects.filter(nave=nave_b, recurso=recurso).exists())

    def test_flujo_completo_ficha_operativa(self):
        """
        Flujo end-to-end:
        1. Crear nave con eslora=20 → Signal crea MatrizNaveRecurso (cantidad=2, visible=True)
        2. Crear recurso con requerimientos=["vigencia", "presion"]
        3. Verificar que PeriodoRevision existe en estado 'pendiente'
        4. Crear ficha con todos los requerimientos cumplidos y estado_operativo=True
        5. Verificar que período pasa a 'en_proceso'
        6. Verificar que _determinar_estado_cierre retorna 'operativo'
        """
        recurso = self._crear_recurso(
            nombre="Extintor Operativo",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Operativa", "INT-011", 20)

        matriz = self._get_matriz(nave, recurso)
        periodo = self._get_periodo(nave)

        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)
        self.assertEqual(periodo.estado, "pendiente")

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True,
                vigencia={"cumple": True, "observacion": ""},
                presion={"cumple": True, "observacion": ""},
            ),
        )

        periodo.refresh_from_db()

        self.assertTrue(ficha.estado_operativo)
        self.assertEqual(periodo.estado, "en_proceso")
        self.assertEqual(MotorPeriodos._determinar_estado_cierre(periodo), "cumplido")

    def test_flujo_completo_ficha_con_fallo(self):
        """
        Flujo end-to-end con fallo:
        1. Crear nave → Signal crea MatrizNaveRecurso
        2. Crear ficha con requerimiento fallado (cumple=False, observacion='motivo')
           y estado_operativo=False
        3. Verificar que período está en 'en_proceso'
        4. Verificar que _determinar_estado_cierre retorna 'fallido'
        """
        recurso = self._crear_recurso(
            nombre="Extintor Con Falla",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Con Falla", "INT-012", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=False,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True,
                vigencia={"cumple": True, "observacion": ""},
                presion={"cumple": False, "observacion": "motivo"},
            ),
        )

        periodo.refresh_from_db()

        self.assertFalse(ficha.estado_operativo)
        self.assertEqual(periodo.estado, "en_proceso")
        self.assertEqual(MotorPeriodos._determinar_estado_cierre(periodo), "cumplido")

    def test_flujo_completo_periodo_vencido(self):
        """
        Período que expira con ficha incompleta → caduco:
        1. Crear ficha parcial (estado_operativo=None, checklist incompleto)
        2. Verificar que _determinar_estado_cierre retorna 'caduco'
        """
        recurso = self._crear_recurso(
            nombre="Extintor Parcial",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Parcial", "INT-013", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True,
                vigencia={"cumple": True, "observacion": ""},
            ),
        )

        self.assertIsNone(ficha.estado_operativo)
        self.assertEqual(MotorPeriodos._determinar_estado_cierre(periodo), "vencido")

    def test_observacion_requerimiento_fallado_es_obligatoria(self):
        """
        Si un requerimiento tiene cumple=False y no tiene observación,
        MotorFichas.crear_ficha debe lanzar ValueError
        """
        recurso = self._crear_recurso(
            nombre="Extintor Sin Observación",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Sin Observación", "INT-014", 20)
        periodo = self._get_periodo(nave)

        with self.assertRaises(ValueError):
            MotorFichas.crear_ficha(
                periodo=periodo,
                recurso=recurso,
                usuario=self.usuario,
                estado_operativo=False,
                observacion_general="",
                payload_checklist=self._payload_con_cantidad(
                    True,
                    vigencia={"cumple": True, "observacion": ""},
                    presion={"cumple": False, "observacion": ""},
                ),
            )

    def test_estado_operativo_se_fuerza_false_si_hay_fallo_en_requerimiento(self):
        """
        Si hay requerimientos fallados, validar_estado_operativo retorna False
        cuando estado_operativo=True
        """
        recurso = self._crear_recurso(
            nombre="Extintor Validación",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )
        definicion = MotorFichas.construir_definicion_checklist(recurso, cantidad=2)

        es_valido = MotorFichas.validar_estado_operativo(
            definicion,
            estado_operativo=True,
            payload_checklist=self._payload_con_cantidad(
                True,
                vigencia={"cumple": True, "observacion": ""},
                presion={"cumple": False, "observacion": "baja presión"},
            ),
        )

        self.assertFalse(es_valido)

    def test_recurso_sin_requerimientos_y_sin_cantidad_sintetica_puede_guardarse_con_payload_vacio(self):
        """
        Un recurso con requerimientos=[] y cantidad<=1 permite payload_checklist={}
        y cualquier valor de estado_operativo.
        """
        recurso_ok = self._crear_recurso(
            nombre="Recurso Sin Checklist OK",
            regla_aplicacion=None,
            requerimientos=[],
        )
        recurso_falla = self._crear_recurso(
            nombre="Recurso Sin Checklist FALLA",
            regla_aplicacion=None,
            requerimientos=[],
        )
        nave = self._crear_nave("Nave Sin Checklist", "INT-015", 20)
        periodo = self._get_periodo(nave)

        ficha_ok = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso_ok,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={},
        )
        ficha_falla = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso_falla,
            usuario=self.usuario,
            estado_operativo=False,
            observacion_general="",
            payload_checklist={},
        )

        self.assertEqual(ficha_ok.payload_checklist, {})
        self.assertTrue(ficha_ok.estado_operativo)
        self.assertEqual(ficha_falla.payload_checklist, {})
        self.assertFalse(ficha_falla.estado_operativo)

    def test_recurso_sin_requerimientos_y_cantidad_mayor_a_uno_exige_requisito_cantidad(self):
        recurso = self._crear_recurso(
            nombre="Recurso Solo Cantidad",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=[],
        )
        nave = self._crear_nave("Nave Solo Cantidad", "INT-018", 20)
        periodo = self._get_periodo(nave)

        with self.assertRaises(ValueError):
            MotorFichas.crear_ficha(
                periodo=periodo,
                recurso=recurso,
                usuario=self.usuario,
                estado_operativo=True,
                observacion_general="",
                payload_checklist={},
            )

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(True),
        )

        self.assertTrue(ficha.estado_operativo)

    def test_guardado_parcial_sin_cantidad_es_permitido(self):
        """
        Un guardado parcial (estado_operativo=None) no debe exigir __cantidad__
        aunque cantidad > 1. La validación completa solo ocurre al confirmar.
        """
        recurso = self._crear_recurso(
            nombre="Recurso Guardado Parcial",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Parcial Cantidad", "INT-021", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist={},
        )

        self.assertIsNone(ficha.estado_operativo)

    def test_calcular_estado_ficha_usa_cantidad(self):
        """
        calcular_estado_ficha debe retornar 'en_progreso' si falta __cantidad__
        cuando cantidad > 1, y 'completa' cuando está presente y cumplida.
        """
        recurso = self._crear_recurso(
            nombre="Recurso Estado Ficha",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        definicion = MotorFichas.construir_definicion_checklist(recurso, cantidad=2)

        estado = MotorFichas.calcular_estado_ficha(
            definicion,
            estado_operativo=True,
            payload_checklist={"vigencia": {"cumple": True, "observacion": ""}},
        )
        self.assertEqual(estado, "en_progreso")

        estado = MotorFichas.calcular_estado_ficha(
            definicion,
            estado_operativo=True,
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": True, "observacion": ""}
            ),
        )
        self.assertEqual(estado, "completa")

    def test_calcular_estado_ficha_distingue_pendiente_y_en_progreso(self):
        recurso = self._crear_recurso(
            nombre="Recurso Estado Parcial",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "operatividad"],
        )
        definicion = MotorFichas.construir_definicion_checklist(recurso, cantidad=0)

        estado = MotorFichas.calcular_estado_ficha(
            definicion,
            estado_operativo=None,
            payload_checklist={},
        )
        self.assertEqual(estado, "pendiente")

        estado = MotorFichas.calcular_estado_ficha(
            definicion,
            estado_operativo=None,
            payload_checklist={"vigencia": {"cumple": True, "observacion": ""}},
        )
        self.assertEqual(estado, "en_progreso")

    def test_crear_ficha_operativa_actualiza_ultimo_estado(self):
        """Crear ficha con estado_operativo=True setea ultimo_estado_operativo=True en matriz."""
        recurso = self._crear_recurso(
            nombre="Recurso Estado Persistente OK",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Estado OK", "INT-030", 20)
        periodo = self._get_periodo(nave)
        matriz = self._get_matriz(nave, recurso)
        self.assertIsNone(matriz.ultimo_estado_operativo)

        MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": True, "observacion": ""}
            ),
        )

        matriz.refresh_from_db()
        self.assertTrue(matriz.ultimo_estado_operativo)
        self.assertIsNotNone(matriz.ultimo_estado_operativo_en)

    def test_modificar_ficha_a_fallada_actualiza_ultimo_estado(self):
        """Modificar ficha a estado_operativo=False actualiza la matriz correctamente."""
        recurso = self._crear_recurso(
            nombre="Recurso Estado Persistente Fallo",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Estado Fallo", "INT-031", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": True, "observacion": ""}
            ),
        )
        MotorFichas.modificar_ficha(
            ficha=ficha,
            usuario_modificador=self.usuario,
            estado_operativo=False,
            observacion_general="sin vigencia",
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": False, "observacion": "sin vigencia"}
            ),
        )

        matriz = self._get_matriz(nave, recurso)
        self.assertFalse(matriz.ultimo_estado_operativo)

    def test_guardado_parcial_desde_null_no_cambia_valor_pero_actualiza_timestamp(self):
        """NULL + prev NULL: el valor queda None, pero el timestamp se actualiza."""
        recurso = self._crear_recurso(
            nombre="Recurso Sin Alterar",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Sin Alterar", "INT-032", 20)
        periodo = self._get_periodo(nave)

        MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist={},
        )

        matriz = self._get_matriz(nave, recurso)
        self.assertIsNone(matriz.ultimo_estado_operativo)
        self.assertIsNotNone(matriz.ultimo_estado_operativo_en)

    def test_fallo_a_fallo_actualiza_timestamp(self):
        """fallo → fallo debe actualizar ultimo_estado_operativo_en aunque el valor no cambie."""
        import time

        recurso = self._crear_recurso(
            nombre="Recurso Fallo Timestamp",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Fallo Timestamp", "INT-033", 20)
        periodo = self._get_periodo(nave)
        payload_fallo = self._payload_con_cantidad(
            True, vigencia={"cumple": False, "observacion": "roto"}
        )

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=False,
            observacion_general="roto",
            payload_checklist=payload_fallo,
        )
        matriz = self._get_matriz(nave, recurso)
        ts_1 = matriz.ultimo_estado_operativo_en

        time.sleep(0.01)

        MotorFichas.modificar_ficha(
            ficha=ficha,
            usuario_modificador=self.usuario,
            estado_operativo=False,
            observacion_general="sigue roto",
            payload_checklist=payload_fallo,
        )
        matriz.refresh_from_db()
        self.assertFalse(matriz.ultimo_estado_operativo)
        self.assertGreater(matriz.ultimo_estado_operativo_en, ts_1)

    def test_recurso_nuevo_no_aparece_en_historial_anterior(self):
        """
        Un recurso creado después del cierre de un período
        no debe aparecer en el historial de ese período.
        """
        from datetime import timedelta
        from sitrep.inspection.presenters import construir_recursos_lista_periodo as _construir_recursos_lista_periodo

        nave = self._crear_nave("Nave Historial Fantasma", "INT-040", 15)
        periodo = self._get_periodo(nave)

        periodo.fecha_termino = timezone.now().date() - timedelta(days=5)
        periodo.estado = "cumplido"
        periodo.save()

        self._crear_recurso(
            nombre="Recurso Fantasma",
            regla_aplicacion=None,
            requerimientos=[],
        )
        MotorReglasSITREP.sincronizar_matriz_nave(nave)

        recursos = _construir_recursos_lista_periodo(nave, periodo, for_history=True)
        nombres = [r["recurso"].nombre for r in recursos]
        self.assertNotIn("Recurso Fantasma", nombres)

    def test_recursos_se_ordenan_por_segundo_tramo_del_codigo_dentro_del_area(self):
        from sitrep.inspection.presenters import construir_recursos_lista_periodo as _construir_recursos_lista_periodo

        area_salvamento = Area.objects.create(nombre="Salvamento")
        area_incendio = Area.objects.create(nombre="Incendio")
        nave = self._crear_nave("Nave Orden Codigos", "INT-041", 15)
        periodo = self._get_periodo(nave)

        self._crear_recurso(
            nombre="Salvamento 15",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.15-Q",
        )
        self._crear_recurso(
            nombre="Salvamento 1",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.1-Q",
        )
        self._crear_recurso(
            nombre="Salvamento 21",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.21-Q",
        )
        self._crear_recurso(
            nombre="Salvamento 8",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.8-Q",
        )
        self._crear_recurso(
            nombre="Incendio 10",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_incendio,
            codigo="2.10-Q",
        )
        self._crear_recurso(
            nombre="Incendio 3",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_incendio,
            codigo="2.3-Q",
        )
        MotorReglasSITREP.sincronizar_matriz_nave(nave)

        recursos = _construir_recursos_lista_periodo(nave, periodo)

        codigos_salvamento = [
            item["recurso"].codigo for item in recursos if item["recurso"].area_id == area_salvamento.id
        ]
        codigos_incendio = [
            item["recurso"].codigo for item in recursos if item["recurso"].area_id == area_incendio.id
        ]

        self.assertEqual(codigos_salvamento, ["1.1-Q", "1.8-Q", "1.15-Q", "1.21-Q"])
        self.assertEqual(codigos_incendio, ["2.3-Q", "2.10-Q"])

    def test_grupos_de_areas_se_ordenan_por_orden_y_no_por_nombre(self):
        from sitrep.inspection.presenters import agrupar_recursos_por_area as _agrupar_recursos_por_area, construir_recursos_lista_periodo as _construir_recursos_lista_periodo

        area_zeta = Area.objects.create(nombre="Zeta", orden=1)
        area_alfa = Area.objects.create(nombre="Alfa", orden=2)
        nave = self._crear_nave("Nave Orden Areas", "INT-042", 15)
        periodo = self._get_periodo(nave)

        self._crear_recurso(
            nombre="Recurso Zeta",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_zeta,
            codigo="9.1-Q",
        )
        self._crear_recurso(
            nombre="Recurso Alfa",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_alfa,
            codigo="1.1-Q",
        )
        MotorReglasSITREP.sincronizar_matriz_nave(nave)

        recursos = _construir_recursos_lista_periodo(nave, periodo)
        grupos = _agrupar_recursos_por_area(recursos)

        self.assertEqual([grupo["area"].id for grupo in grupos], [area_zeta.id, area_alfa.id])

    def test_registros_se_ordenan_por_codigo_dentro_del_area(self):
        from sitrep.inspection.presenters import agrupar_registros_por_area as _agrupar_registros_por_area

        area_salvamento = Area.objects.create(nombre="Salvamento")
        recurso_15 = self._crear_recurso(
            nombre="Salvamento 15",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.15-Q",
        )
        recurso_1 = self._crear_recurso(
            nombre="Salvamento 1",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.1-Q",
        )
        recurso_21 = self._crear_recurso(
            nombre="Salvamento 21",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.21-Q",
        )
        recurso_8 = self._crear_recurso(
            nombre="Salvamento 8",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.8-Q",
        )

        grupos = _agrupar_registros_por_area(
            [
                {"tipo": "pendiente", "recurso": recurso_15},
                {"tipo": "pendiente", "recurso": recurso_1},
                {"tipo": "pendiente", "recurso": recurso_21},
                {"tipo": "pendiente", "recurso": recurso_8},
            ]
        )

        self.assertEqual(
            [registro["recurso"].codigo for registro in grupos[0]["registros"]],
            ["1.1-Q", "1.8-Q", "1.15-Q", "1.21-Q"],
        )

    def test_numero_periodo_se_calcula_con_reset_anual_desde_agregado_en(self):
        from sitrep.inspection.presenters import numero_periodo as _numero_periodo

        nave = self._crear_nave("Nave Periodos", "INT-043", 15)
        nave.agregado_en = timezone.make_aware(datetime(2026, 1, 1, 9, 0, 0))

        periodo_1 = PeriodoRevision(
            nave=nave,
            periodicidad=self.periodicidad,
            fecha_inicio=date(2026, 1, 1),
            fecha_termino=date(2026, 1, 7),
        )
        periodo_12 = PeriodoRevision(
            nave=nave,
            periodicidad=self.periodicidad,
            fecha_inicio=date(2026, 3, 19),
            fecha_termino=date(2026, 3, 25),
        )
        periodo_reset = PeriodoRevision(
            nave=nave,
            periodicidad=self.periodicidad,
            fecha_inicio=date(2026, 12, 31),
            fecha_termino=date(2027, 1, 6),
        )
        periodo_anterior = PeriodoRevision(
            nave=nave,
            periodicidad=self.periodicidad,
            fecha_inicio=date(2025, 12, 25),
            fecha_termino=date(2025, 12, 31),
        )

        self.assertEqual(_numero_periodo(periodo_1, nave), 1)
        self.assertEqual(_numero_periodo(periodo_12, nave), 12)
        self.assertEqual(_numero_periodo(periodo_reset, nave), 1)
        self.assertIsNone(_numero_periodo(periodo_anterior, nave))

    def test_construir_recursos_lista_periodo_expone_estado_ficha_pendiente(self):
        from sitrep.inspection.presenters import construir_recursos_lista_periodo as _construir_recursos_lista_periodo

        recurso = self._crear_recurso(
            nombre="Recurso Pendiente Persistido",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Estado Ficha", "INT-044", 20)
        periodo = self._get_periodo(nave)
        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist={},
        )
        ficha.estado_ficha = "pendiente"
        ficha.save(update_fields=["estado_ficha"])

        recursos = _construir_recursos_lista_periodo(nave, periodo)
        item = next(item for item in recursos if item["recurso"].id == recurso.id)

        self.assertTrue(item["tiene_ficha"])
        self.assertEqual(item["estado_ficha"], "pendiente")
        self.assertIsNone(item["estado_operativo"])

    def test_requisito_cantidad_fallado_exige_observacion(self):
        recurso = self._crear_recurso(
            nombre="Recurso Cantidad Fallida",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=[],
        )
        nave = self._crear_nave("Nave Cantidad Fallida", "INT-019", 20)
        periodo = self._get_periodo(nave)

        with self.assertRaises(ValueError):
            MotorFichas.crear_ficha(
                periodo=periodo,
                recurso=recurso,
                usuario=self.usuario,
                estado_operativo=False,
                observacion_general="",
                payload_checklist={
                    MotorFichas.CANTIDAD_REQUISITO_KEY: {
                        "cumple": False,
                        "observacion": "",
                    }
                },
            )

    def test_construir_checklist_items_agrega_cantidad_al_final(self):
        recurso = self._crear_recurso(
            nombre="Recurso Checklist Cantidad",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )

        definicion = MotorFichas.construir_definicion_checklist(recurso, cantidad=4)
        checklist = MotorFichas.construir_checklist_items(definicion, {})

        self.assertEqual(
            [item["key"] for item in checklist],
            ["vigencia", "presion", MotorFichas.CANTIDAD_REQUISITO_KEY],
        )
        self.assertEqual(checklist[-1]["label"], "Cantidad: 4")

    def test_requerimiento_tipo_condicion_usa_label_fijo(self):
        """Un requerimiento tipo 'condicion' se valida como cualquier otro,
        pero su label es fijo ('Condición.') y no depende del texto del editor."""
        recurso = Recurso.objects.create(
            categoria="Seguridad", tipo="Material",
            periodicidad=self.periodicidad,
            nombre="Bote Salvavidas Condición",
            requerimientos=[{"id": "condicion_1", "tipo": "condicion"}],
            regla_aplicacion=None,
            catalogo_version=self.catalogo_version,
        )

        definicion = MotorFichas.construir_definicion_checklist(recurso, cantidad=0)
        checklist = MotorFichas.construir_checklist_items(definicion, {})

        self.assertEqual([item["key"] for item in checklist], ["condicion_1"])
        self.assertEqual(checklist[0]["label"], "Condición.")

    def test_cantidad_no_aparece_si_no_esta_marcada_en_el_catalogo(self):
        """Presencia de 'cantidad' depende del catálogo (editor), no del valor
        calculado por el motor de reglas — aunque cantidad>1, si el recurso no
        declaró el requerimiento 'cantidad' en su catálogo, no aparece."""
        recurso = Recurso.objects.create(
            categoria="Seguridad", tipo="Material",
            periodicidad=self.periodicidad,
            nombre="Recurso Sin Cantidad En Catalogo",
            requerimientos=requerimientos_estandar("vigencia"),
            regla_aplicacion=None,
            catalogo_version=self.catalogo_version,
        )

        definicion = MotorFichas.construir_definicion_checklist(recurso, cantidad=4)
        checklist = MotorFichas.construir_checklist_items(definicion, {})

        self.assertEqual([item["key"] for item in checklist], ["vigencia"])

    def test_cantidad_aparece_si_esta_marcada_en_el_catalogo(self):
        recurso = Recurso.objects.create(
            categoria="Seguridad", tipo="Material",
            periodicidad=self.periodicidad,
            nombre="Recurso Con Cantidad En Catalogo",
            requerimientos=[{"id": MotorFichas.CANTIDAD_REQUISITO_KEY, "tipo": "cantidad"}],
            regla_aplicacion=None,
            catalogo_version=self.catalogo_version,
        )

        definicion = MotorFichas.construir_definicion_checklist(recurso, cantidad=0)
        checklist = MotorFichas.construir_checklist_items(definicion, {})

        self.assertEqual([item["key"] for item in checklist], [MotorFichas.CANTIDAD_REQUISITO_KEY])
        self.assertEqual(checklist[0]["label"], "Cantidad: 0")

    def test_ficha_legacy_sin_requisito_cantidad_sigue_completa(self):
        """Un recurso cuyo catálogo no declara el requerimiento 'cantidad'
        (aunque tenga motor de reglas) no lo exige para estar completa."""
        recurso = self._crear_recurso(
            nombre="Recurso Legacy Cantidad",
            regla_aplicacion=None,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Legacy Cantidad", "INT-020", 20)
        periodo = self._get_periodo(nave)

        ficha = FichaRegistro.objects.create(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            payload_checklist={
                "vigencia": {"cumple": True, "observacion": ""},
                "presion": {"cumple": True, "observacion": ""},
            },
        )

        self.assertTrue(MotorPeriodos._es_ficha_completa(ficha))

    def test_crear_ficha_congela_definicion_checklist(self):
        """crear_ficha guarda un snapshot de la definición, no solo el payload."""
        recurso = self._crear_recurso(
            nombre="Recurso Snapshot",
            regla_aplicacion=None,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Snapshot", "INT-070", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist={},
        )

        self.assertEqual(
            ficha.definicion_checklist,
            MotorFichas.construir_definicion_checklist(recurso, cantidad=0),
        )

    def test_ficha_existente_ignora_requerimiento_agregado_despues_al_catalogo(self):
        """Si el catálogo agrega un requerimiento después de crear la ficha, esa
        ficha ya abierta no lo exige — sigue validando contra su snapshot."""
        recurso = self._crear_recurso(
            nombre="Recurso Catalogo Cambia",
            regla_aplicacion=None,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Catalogo Cambia", "INT-071", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={"vigencia": {"cumple": True, "observacion": ""}},
        )
        self.assertTrue(MotorPeriodos._es_ficha_completa(ficha))

        # El editor agrega un requerimiento nuevo al catálogo mientras el período sigue abierto.
        recurso.requerimientos = requerimientos_estandar("vigencia", "presion")
        recurso.save(update_fields=["requerimientos"])

        # La ficha ya creada no se entera — sigue completa contra lo que existía al crearla.
        ficha.refresh_from_db()
        self.assertTrue(MotorPeriodos._es_ficha_completa(ficha))
        definicion = MotorFichas.obtener_definicion_checklist(recurso, 0, ficha=ficha)
        self.assertEqual([item["key"] for item in definicion], ["vigencia"])

    def test_modificar_ficha_usa_definicion_congelada_no_la_recalcula(self):
        """modificar_ficha valida contra el snapshot tomado al crear, no contra
        el catálogo en vivo — aunque éste haya cambiado mientras tanto."""
        recurso = self._crear_recurso(
            nombre="Recurso Modificar Snapshot",
            regla_aplicacion=None,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Modificar Snapshot", "INT-072", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist={"vigencia": {"cumple": True, "observacion": ""}},
        )

        # El editor quita "presion" del catálogo mientras el período sigue abierto.
        recurso.requerimientos = requerimientos_estandar("vigencia")
        recurso.save(update_fields=["requerimientos"])

        # modificar_ficha sigue exigiendo "presion" — viene del snapshot, no del catálogo actual.
        with self.assertRaises(ValueError):
            MotorFichas.modificar_ficha(
                ficha=ficha,
                usuario_modificador=self.usuario,
                estado_operativo=True,
                observacion_general="",
                payload_checklist={"vigencia": {"cumple": True, "observacion": ""}},
            )

    def test_obtener_definicion_checklist_sin_ficha_usa_catalogo_en_vivo(self):
        """Sin ficha (todavía no se creó), obtener_definicion_checklist refleja
        el catálogo actual — recién se congela cuando la ficha existe."""
        recurso = self._crear_recurso(
            nombre="Recurso Sin Ficha Aun",
            regla_aplicacion=None,
            requerimientos=["vigencia"],
        )

        definicion = MotorFichas.obtener_definicion_checklist(recurso, 0, ficha=None)
        self.assertEqual([item["key"] for item in definicion], ["vigencia"])

    def test_obtener_definicion_checklist_ficha_sin_snapshot_usa_catalogo_en_vivo(self):
        """Una ficha anterior a este campo (definicion_checklist=None) cae al
        catálogo en vivo — retrocompatible con fichas ya existentes."""
        recurso = self._crear_recurso(
            nombre="Recurso Ficha Legacy",
            regla_aplicacion=None,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Ficha Legacy", "INT-073", 20)
        periodo = self._get_periodo(nave)
        ficha_legacy = FichaRegistro.objects.create(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            payload_checklist={"vigencia": {"cumple": True, "observacion": ""}},
        )
        self.assertIsNone(ficha_legacy.definicion_checklist)

        definicion = MotorFichas.obtener_definicion_checklist(recurso, 0, ficha=ficha_legacy)
        self.assertEqual([item["key"] for item in definicion], ["vigencia"])

    def test_regla_con_atributo_inexistente_usa_fallback(self):
        """regla_aplicacion con atributo='campo_inexistente' retorna fallback"""
        recurso = self._crear_recurso(
            nombre="Recurso Atributo Inválido",
            regla_aplicacion={
                "atributo": "campo_inexistente",
                "condiciones": [
                    {
                        "operador": "<=",
                        "valor": 10,
                        "resultado_cantidad": 99,
                        "resultado_visible": True,
                    }
                ],
                "fallback_cantidad": 7,
                "fallback_visible": False,
            },
        )
        nave = self._crear_nave("Nave Fallback Regla", "INT-016", 20)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 7)
        self.assertFalse(matriz.es_visible)

    def test_regla_con_operador_invalido_ignora_condicion(self):
        """Una condición con operador no reconocido se ignora y continúa evaluando"""
        recurso = self._crear_recurso(
            nombre="Recurso Operador Inválido",
            regla_aplicacion={
                "atributo": "eslora",
                "condiciones": [
                    {
                        "operador": "!==",
                        "valor": 20,
                        "resultado_cantidad": 99,
                        "resultado_visible": False,
                    },
                    {
                        "operador": "<=",
                        "valor": 30,
                        "resultado_cantidad": 2,
                        "resultado_visible": True,
                    },
                ],
                "fallback_cantidad": 0,
                "fallback_visible": False,
            },
        )
        nave = self._crear_nave("Nave Operador Inválido", "INT-017", 20)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_payload_checklist_legacy_booleano_se_normaliza(self):
        """
        Un payload legacy {"req": True} debe normalizarse a {"req": {"cumple": True, "observacion": ""}}
        mediante MotorFichas.normalizar_payload_checklist()
        """
        payload_normalizado = MotorFichas.normalizar_payload_checklist({"req": True})

        self.assertEqual(
            payload_normalizado,
            {"req": {"cumple": True, "observacion": ""}},
        )

    def test_payload_checklist_sin_campo_observacion_se_completa(self):
        """
        Un payload {"req": {"cumple": True}} sin "observacion" debe normalizarse
        agregando "observacion": ""
        """
        payload_normalizado = MotorFichas.normalizar_payload_checklist(
            {"req": {"cumple": True}}
        )

        self.assertEqual(
            payload_normalizado,
            {"req": {"cumple": True, "observacion": ""}},
        )

    def test_fallo_nuevo_al_pasar_de_operativo_a_fallo(self):
        """operativo → fallo en mismo período = es_fallo_nuevo True."""
        recurso = self._crear_recurso("Recurso Fallo Nuevo", None, ["vigencia"])
        nave = self._crear_nave("Nave Fallo Nuevo", "INT-060", 15)
        periodo = self._get_periodo(nave)
        matriz = self._get_matriz(nave, recurso)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo, recurso=recurso, usuario=self.usuario,
            estado_operativo=True, observacion_general="",
            payload_checklist={"vigencia": {"cumple": True, "observacion": ""}},
        )
        matriz.refresh_from_db()
        matriz.ultimo_estado_operativo_anterior = True
        matriz.save(update_fields=["ultimo_estado_operativo_anterior"])

        MotorFichas.modificar_ficha(
            ficha=ficha, usuario_modificador=self.usuario,
            estado_operativo=False, observacion_general="roto",
            payload_checklist={"vigencia": {"cumple": False, "observacion": "roto"}},
        )
        matriz.refresh_from_db()
        self.assertTrue(matriz.es_fallo_nuevo)

    def test_fallo_a_fallo_no_es_fallo_nuevo(self):
        """fallo → fallo en mismo período NO debe marcar es_fallo_nuevo."""
        recurso = self._crear_recurso("Recurso Fallo Persistente", None, ["vigencia"])
        nave = self._crear_nave("Nave Fallo Persistente", "INT-061", 15)
        periodo = self._get_periodo(nave)
        matriz = self._get_matriz(nave, recurso)

        matriz.ultimo_estado_operativo_anterior = False
        matriz.ultimo_estado_operativo = False
        matriz.save(update_fields=["ultimo_estado_operativo_anterior", "ultimo_estado_operativo"])

        MotorFichas.crear_ficha(
            periodo=periodo, recurso=recurso, usuario=self.usuario,
            estado_operativo=False, observacion_general="sigue roto",
            payload_checklist={"vigencia": {"cumple": False, "observacion": "sigue roto"}},
        )
        matriz.refresh_from_db()
        self.assertFalse(matriz.es_fallo_nuevo)

    def test_cierre_periodo_hace_snapshot_y_expira_fallos(self):
        """Al cerrar período: snapshot de estado y expiración de fallos nuevos sin ficha."""
        recurso = self._crear_recurso("Recurso Cierre", None, ["vigencia"])
        nave = self._crear_nave("Nave Cierre", "INT-062", 15)
        periodo = self._get_periodo(nave)
        matriz = self._get_matriz(nave, recurso)

        matriz.ultimo_estado_operativo = False
        matriz.es_fallo_nuevo = True
        matriz.save(update_fields=["ultimo_estado_operativo", "es_fallo_nuevo"])

        MotorPeriodos._cerrar_periodo(periodo)

        matriz.refresh_from_db()
        self.assertFalse(matriz.ultimo_estado_operativo_anterior)
        self.assertFalse(matriz.es_fallo_nuevo)

    def test_derivar_fallo_con_checklist_parcial(self):
        """Fallo >= 1 → FALLO aunque haya items sin responder."""
        recurso = self._crear_recurso(
            nombre="Recurso Fallo Parcial",
            regla_aplicacion=None,
            requerimientos=["vigencia", "presion"],
        )
        payload = {"vigencia": {"cumple": False, "observacion": "vencida"}}
        definicion = MotorFichas.construir_definicion_checklist(recurso, cantidad=0)
        resultado = MotorFichas.derivar_estado_operativo_desde_checklist(definicion, payload)
        self.assertIs(resultado, False)

    def test_require_cumple_rechaza_cumple_null(self):
        """cumple:null debe contar como item faltante en require_cumple=True."""
        recurso = self._crear_recurso(
            nombre="Recurso Cumple Null",
            regla_aplicacion=None,
            requerimientos=["vigencia"],
        )
        payload = {"vigencia": {"cumple": None, "observacion": ""}}
        definicion = MotorFichas.construir_definicion_checklist(recurso, cantidad=0)
        es_valido, faltantes = MotorFichas.validar_payload_checklist(
            definicion, payload, require_cumple=True
        )
        self.assertFalse(es_valido)
        self.assertTrue(len(faltantes) > 0)

    def test_crear_ficha_completa_tiene_estado_ficha_completa(self):
        """crear_ficha con payload completo y estado_operativo definido → estado_ficha='completa'."""
        recurso = self._crear_recurso(
            nombre="Recurso Ficha Completa",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Ficha Completa", "INT-063", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": True, "observacion": ""}
            ),
        )
        self.assertEqual(ficha.estado_ficha, "completa")

    def test_operativo_mas_null_resetea_matriz_a_null(self):
        """OPERATIVO + NULL = NULL: la matriz debe quedar en None."""
        recurso = self._crear_recurso(
            nombre="Recurso Reset NULL",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Reset NULL", "INT-064", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": True, "observacion": ""}
            ),
        )
        matriz = self._get_matriz(nave, recurso)
        self.assertTrue(matriz.ultimo_estado_operativo)

        MotorFichas.modificar_ficha(
            ficha=ficha,
            usuario_modificador=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist={},
        )
        matriz.refresh_from_db()
        self.assertIsNone(matriz.ultimo_estado_operativo)

    def test_fallo_mas_null_mantiene_fallo_en_matriz(self):
        """FALLO + NULL = FALLO: la matriz debe permanecer en False."""
        recurso = self._crear_recurso(
            nombre="Recurso Fallo Persistente",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Fallo Persistente", "INT-065", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=False,
            observacion_general="roto",
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": False, "observacion": "roto"}
            ),
        )
        matriz = self._get_matriz(nave, recurso)
        self.assertFalse(matriz.ultimo_estado_operativo)

        MotorFichas.modificar_ficha(
            ficha=ficha,
            usuario_modificador=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist={},
        )
        matriz.refresh_from_db()
        self.assertFalse(matriz.ultimo_estado_operativo)


class TestPeriodoRevisionVersionPinning(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(nombre="Naviera P", rut="77777777-7", slug="naviera-p")
        # ponytail: brief's setUp omitted this — versiones_vigentes() legitimately
        # returns central=None when no central CatalogoVersion row exists at all
        # (verified against sitrep/catalog/services.py), so without a central
        # version the "primer periodo pinnea version central" test is untestable.
        # Matches the fixture pattern already used by TestMotorPeriodosEstados /
        # TestIntegracionMotorReglas in this same file.
        self.catalogo_version = CatalogoVersion.crear_para_scope()
        self.nave = Nave.objects.create(
            naviera=self.naviera, nombre="Nave P", matricula="NVP-001",
            eslora=25.0, arqueo_bruto=300, capacidad_personas=20,
        )
        self.periodicidad = Periodicidad.objects.create(nombre="Semanal", duracion_dias=7, offset_dias=1, responsabilidad="mar", visibilidad="todos")

    def test_primer_periodo_pinnea_version_central_1(self):
        MotorPeriodos.sincronizar_periodos_nave(self.nave)
        periodo = PeriodoRevision.objects.get(nave=self.nave, periodicidad=self.periodicidad)
        self.assertIsNotNone(periodo.catalogo_version_central)
        self.assertIsNone(periodo.catalogo_version_naviera)
        self.assertIsNone(periodo.catalogo_version_nave)

    def test_periodo_en_naviera_independiente_no_pinnea_central(self):
        self.naviera.catalogo_independiente = True
        self.naviera.save(update_fields=['catalogo_independiente'])
        MotorPeriodos.sincronizar_periodos_nave(self.nave)
        periodo = PeriodoRevision.objects.get(nave=self.nave, periodicidad=self.periodicidad)
        self.assertIsNone(periodo.catalogo_version_central)


class TestFichaPdfTemplate(TestCase):
    """ponytail: DB-free render_to_string check — catches the requerimientos-dict-repr
    regression (template must read checklist_items, not raw recurso.requerimientos)."""

    def test_renderiza_labels_numerados_en_orden_o_f_p_obs(self):
        from django.template.loader import render_to_string

        areas_grupos = [{
            "nombre_display": "Salvamento",
            "area_color": {"bg": "#000", "text": "#fff", "bg_light": "#eee"},
            "recursos": [{
                "recurso": {"codigo": "3.3", "nombre": "Balsa salvavidas"},
                "checklist_items": [
                    {"key": "vigencia", "label": "Vigencia vigente"},
                    {"key": "condicion_1", "label": "Condición."},
                ],
            }],
        }]
        html = render_to_string(
            "inspection/kiosco/ficha_pdf.html",
            {
                "nave": {"nombre": "Nave Test", "matricula": "NVT-1"},
                "naviera": {"nombre": "Naviera Test"},
                "periodo": {
                    "periodicidad": {"nombre": "Semanal"},
                    "fecha_inicio": date(2026, 1, 1),
                    "fecha_termino": date(2026, 1, 8),
                },
                "areas_grupos": areas_grupos,
            },
        )

        self.assertIn("3.3.1", html)
        self.assertIn("3.3.2", html)
        self.assertIn("Vigencia vigente", html)
        self.assertIn("Condición.", html)
        # el bug viejo imprimía el repr del dict crudo de requerimientos
        self.assertNotIn("'tipo':", html)

        pos_o = html.index(">O<")
        pos_f = html.index(">F<")
        pos_p = html.index(">P<")
        pos_obs = html.index("Observación")
        self.assertTrue(pos_o < pos_f < pos_p < pos_obs)


class _FakeSession(dict):
    session_key = "test-session"


class TestKioscoPeriodoPdfView(TestCase):
    """Cubre la lógica nueva de kiosco_periodo_pdf: filtro de áreas por
    query param y flag modo_bn. Mockea weasyprint.HTML para no depender
    de las librerías nativas ni pagar el costo de un render real."""

    def setUp(self):
        self.naviera = Naviera.objects.create(nombre="Naviera PDF", rut="88888888-8", slug="naviera-pdf")
        self.periodicidad = Periodicidad.objects.create(
            nombre="Semanal PDF", duracion_dias=7, offset_dias=1, responsabilidad="mar", visibilidad="todos"
        )
        self.catalogo_version = CatalogoVersion.crear_para_scope()
        self.area_a = Area.objects.create(nombre="Salvamento PDF")
        self.area_b = Area.objects.create(nombre="Incendio PDF")
        Recurso.objects.create(
            categoria="Seguridad", tipo="Material", periodicidad=self.periodicidad, area=self.area_a,
            nombre="Balsa", codigo="1.1", requerimientos=requerimientos_estandar("Vigencia"),
            catalogo_version=self.catalogo_version,
        )
        Recurso.objects.create(
            categoria="Seguridad", tipo="Material", periodicidad=self.periodicidad, area=self.area_b,
            nombre="Extintor", codigo="2.1", requerimientos=requerimientos_estandar("Vigencia"),
            catalogo_version=self.catalogo_version,
        )
        self.usuario = Usuario.objects.create_user(
            username="capitan_pdf", password="password-segura-123", naviera=self.naviera,
            rut="88888888-8", email="capitan_pdf@example.com", rol="capitan",
        )
        self.nave = Nave.objects.create(
            naviera=self.naviera, nombre="Nave PDF", matricula="PDF-001",
            eslora=25.0, arqueo_bruto=300, capacidad_personas=20,
        )
        self.periodo = PeriodoRevision.objects.get(nave=self.nave, periodicidad=self.periodicidad)

    def _llamar_vista(self, query):
        from django.test import RequestFactory
        from sitrep.inspection.views.kiosco import kiosco_periodo_pdf

        request = RequestFactory().get(
            f"/naviera-pdf/kiosco/periodos/{self.periodo.id}/pdf/", query
        )
        request.user = self.usuario
        request.naviera = self.naviera
        request.session = _FakeSession({"nave_id": self.nave.id})

        captured = {}
        with patch("sitrep.inspection.views.pdf.render_to_string") as mock_render, \
                patch("sitrep.inspection.views.pdf.HTML") as mock_html_cls:
            mock_render.return_value = "<html></html>"
            mock_html_cls.return_value.write_pdf.return_value = None
            response = kiosco_periodo_pdf(request, slug="naviera-pdf", periodo_id=self.periodo.id)
            captured["context"] = mock_render.call_args[0][1]
        return response, captured["context"]

    def test_sin_filtro_incluye_todas_las_areas_en_color(self):
        response, context = self._llamar_vista({})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(context["areas_grupos"]), 2)
        self.assertFalse(context["modo_bn"])

    def test_filtro_areas_deja_solo_la_seleccionada(self):
        response, context = self._llamar_vista({"areas": str(self.area_a.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(context["areas_grupos"]), 1)
        self.assertEqual(context["areas_grupos"][0]["area"].id, self.area_a.id)

    def test_modo_bn_activa_flag_en_contexto(self):
        response, context = self._llamar_vista({"modo": "bn"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(context["modo_bn"])


class TestNavePeriodoPdfView(TestCase):
    """Cubre nave_periodo_pdf: el mismo PDF de kiosco_periodo_pdf pero invocado
    desde tierra (sin sesión de nave), con el scoping de capitán."""

    def setUp(self):
        self.naviera = Naviera.objects.create(nombre="Naviera PDF Tierra", rut="77777777-7", slug="naviera-pdf-tierra")
        self.periodicidad = Periodicidad.objects.create(
            nombre="Semanal PDF Tierra", duracion_dias=7, offset_dias=1, responsabilidad="mar", visibilidad="todos"
        )
        self.catalogo_version = CatalogoVersion.crear_para_scope()
        Recurso.objects.create(
            categoria="Seguridad", tipo="Material", periodicidad=self.periodicidad,
            nombre="Balsa", codigo="1.1", requerimientos=requerimientos_estandar("Vigencia"),
            catalogo_version=self.catalogo_version,
        )
        self.nave = Nave.objects.create(
            naviera=self.naviera, nombre="Nave PDF Tierra", matricula="PDFT-001",
            eslora=25.0, arqueo_bruto=300, capacidad_personas=20,
        )
        self.otra_nave = Nave.objects.create(
            naviera=self.naviera, nombre="Otra Nave", matricula="PDFT-002",
            eslora=25.0, arqueo_bruto=300, capacidad_personas=20,
        )
        self.periodo = PeriodoRevision.objects.get(nave=self.nave, periodicidad=self.periodicidad)
        self.admin = Usuario.objects.create_user(
            username="admin_pdf_tierra", password="password-segura-123", naviera=self.naviera,
            rut="77777777-7", email="admin_pdf_tierra@example.com", rol="admin_naviera",
        )
        self.capitan = Usuario.objects.create_user(
            username="capitan_pdf_tierra", password="password-segura-123", naviera=self.naviera,
            rut="77777777-8", email="capitan_pdf_tierra@example.com", rol="capitan",
        )
        Tripulacion.objects.create(usuario=self.capitan, nave=self.otra_nave)

    def _llamar_vista(self, usuario, nave):
        from django.test import RequestFactory
        from sitrep.inspection.views.tierra import nave_periodo_pdf

        periodo = PeriodoRevision.objects.get(nave=nave, periodicidad=self.periodicidad)
        request = RequestFactory().get(
            f"/naviera-pdf-tierra/naves/{nave.id}/periodos/{periodo.id}/pdf/"
        )
        request.user = usuario
        request.naviera = self.naviera
        request.session = _FakeSession()

        with patch("sitrep.inspection.views.pdf.render_to_string") as mock_render, \
                patch("sitrep.inspection.views.pdf.HTML") as mock_html_cls:
            mock_render.return_value = "<html></html>"
            mock_html_cls.return_value.write_pdf.return_value = None
            return nave_periodo_pdf(request, slug="naviera-pdf-tierra", nave_id=nave.id, periodo_id=periodo.id)

    def test_admin_naviera_puede_imprimir_cualquier_nave(self):
        response = self._llamar_vista(self.admin, self.nave)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_capitan_sin_la_nave_recibe_403(self):
        response = self._llamar_vista(self.capitan, self.nave)
        self.assertEqual(response.status_code, 403)

    def test_capitan_con_la_nave_puede_imprimir(self):
        response = self._llamar_vista(self.capitan, self.otra_nave)
        self.assertEqual(response.status_code, 200)


class TestNaveDetalleResoluciones(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(nombre="Naviera Resol", rut="44444444-4", slug="naviera-resol")
        self.nave = Nave.objects.create(
            naviera=self.naviera, nombre="Nave Resol", matricula="NVR-001",
            eslora=20.0, arqueo_bruto=200, capacidad_personas=15,
        )
        self.admin = Usuario.objects.create_user(
            username="admin_resol", password="password-seguro-123", naviera=self.naviera,
            rut="44444444-4", email="admin_resol@example.com", rol="admin_naviera",
        )
        self.periodicidad = Periodicidad.objects.create(
            nombre="Semanal", duracion_dias=7, offset_dias=1, responsabilidad="mar", visibilidad="todos",
        )
        self.catalogo_version = CatalogoVersion.crear_para_scope()
        self.recurso = Recurso.objects.create(
            categoria="Seguridad", tipo="Material", periodicidad=self.periodicidad,
            nombre="Extintor", requerimientos=[], regla_aplicacion={},
            catalogo_version=self.catalogo_version,
        )

    def test_context_incluye_resoluciones_nave(self):
        MatrizNaveRecurso.objects.create(
            nave=self.nave, recurso=self.recurso, cantidad=1, es_visible=True,
            ultimo_estado_operativo=True, ultimo_estado_operativo_anterior=False,
        )
        self.client.force_login(self.admin)
        url = reverse("inventory:nave_detalle", kwargs={"slug": self.naviera.slug, "nave_id": self.nave.id})

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["resoluciones_nave"], 1)
        self.assertContains(response, "Resoluciones")


class TestConstruirHitosInminentes(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Hitos",
            rut="55555555-7",
            slug="naviera-hitos",
        )
        self.periodicidad = Periodicidad.objects.create(
            nombre="Mensual",
            duracion_dias=30,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )
        self.catalogo_version = CatalogoVersion.crear_para_scope()
        self.recurso_a = Recurso.objects.create(
            categoria="Seguridad", tipo="Material",
            periodicidad=self.periodicidad,
            nombre="Extintor A",
            requerimientos=requerimientos_estandar("vigencia", "presion"),
            regla_aplicacion=None,
            catalogo_version=self.catalogo_version,
        )
        self.recurso_b = Recurso.objects.create(
            categoria="Seguridad", tipo="Material",
            periodicidad=self.periodicidad,
            nombre="Extintor B",
            requerimientos=requerimientos_estandar("sello"),
            regla_aplicacion=None,
            catalogo_version=self.catalogo_version,
        )
        self.recurso_sin_checklist = Recurso.objects.create(
            categoria="Seguridad", tipo="Material",
            periodicidad=self.periodicidad,
            nombre="Radio VHF",
            requerimientos=[],
            regla_aplicacion=None,
            catalogo_version=self.catalogo_version,
        )
        self.usuario = Usuario.objects.create_user(
            username="marinero_hitos",
            password="password-seguro-123",
            naviera=self.naviera,
            rut="55555555-8",
            email="marinero_hitos@example.com",
            rol="mar",
        )
        self.nave = Nave.objects.create(
            naviera=self.naviera,
            nombre="Nave Hitos",
            matricula="NVH-001",
            eslora=20.0,
            arqueo_bruto=200,
            capacidad_personas=12,
        )
        self.periodo = PeriodoRevision.objects.get(
            nave=self.nave,
            periodicidad=self.periodicidad,
        )
        hoy = date.today()
        self.lunes = hoy - timedelta(days=hoy.weekday())
        self.domingo_prox = self.lunes + timedelta(days=13)

    def _set_fecha_termino(self, fecha):
        self.periodo.fecha_termino = fecha
        self.periodo.save(update_fields=["fecha_termino"])

    def test_incluye_borde_inicio_de_ventana(self):
        self._set_fecha_termino(self.lunes)
        hitos = construir_hitos_inminentes(self.naviera)
        self.assertEqual([h["id"] for h in hitos], [self.periodo.id])

    def test_incluye_borde_fin_de_ventana(self):
        self._set_fecha_termino(self.domingo_prox)
        hitos = construir_hitos_inminentes(self.naviera)
        self.assertEqual([h["id"] for h in hitos], [self.periodo.id])

    def test_excluye_justo_antes_de_la_ventana(self):
        self._set_fecha_termino(self.lunes - timedelta(days=1))
        self.assertEqual(construir_hitos_inminentes(self.naviera), [])

    def test_excluye_justo_despues_de_la_ventana(self):
        self._set_fecha_termino(self.domingo_prox + timedelta(days=1))
        self.assertEqual(construir_hitos_inminentes(self.naviera), [])

    def test_avance_refleja_fichas_completas_sobre_total_recursos(self):
        self._set_fecha_termino(self.domingo_prox)
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_sin_checklist,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={},
        )

        hitos = construir_hitos_inminentes(self.naviera)

        self.assertEqual(len(hitos), 1)
        self.assertEqual(hitos[0]["nave"], self.nave.nombre)
        self.assertEqual(hitos[0]["periodicidad"], self.periodicidad.nombre)
        self.assertEqual(hitos[0]["avance"], round(100 / 3))


class TestNaveActividadView(TenantFixturesMixin, TestCase):
    def test_dias_densos_para_52_semanas(self):
        self.client.force_login(self.admin_a)
        url = reverse(
            "inventory:api_nave_actividad",
            kwargs={"slug": self.naviera_a.slug, "nave_id": self.nave_a.id},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        dias = response.json()
        self.assertEqual(len(dias), 52 * 7)
        self.assertTrue(all(d["count"] == 0 for d in dias))

    def test_nave_de_otro_tenant_retorna_404(self):
        self.client.force_login(self.admin_a)
        url = reverse(
            "inventory:api_nave_actividad",
            kwargs={"slug": self.naviera_a.slug, "nave_id": self.nave_b.id},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_capitan_sin_la_nave_recibe_403(self):
        capitan = Usuario.objects.create_user(
            username="capitan_actividad", password="password-seguro-123", naviera=self.naviera_a,
            rut="99999999-9", email="capitan_actividad@example.com", rol="capitan",
        )
        self.client.force_login(capitan)
        url = reverse(
            "inventory:api_nave_actividad",
            kwargs={"slug": self.naviera_a.slug, "nave_id": self.nave_a.id},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)

    def test_mar_no_puede_acceder(self):
        mar = Usuario.objects.create_user(
            username="mar_actividad", password="password-seguro-123", naviera=self.naviera_a,
            rut="88888888-8", email="mar_actividad@example.com", rol="mar",
        )
        self.client.force_login(mar)
        url = reverse(
            "inventory:api_nave_actividad",
            kwargs={"slug": self.naviera_a.slug, "nave_id": self.nave_a.id},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)
