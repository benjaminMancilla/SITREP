from unittest import skipUnless

from django.db import IntegrityError, connection, transaction as db_transaction
from django.test import TestCase

from sitrep.accounts.models import Naviera
from sitrep.fleet.models import Nave
from sitrep.catalog.models import CatalogoVersion, Periodicidad, Proposito, Recurso
from sitrep.catalog.services import (
    CatalogoEditorService,
    CatalogoResolver,
    CatalogRuleEngine,
    construir_label_requerimiento,
    requerimientos_estandar,
)


class TestCatalogRuleEngine(TestCase):
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

    def test_evaluar_regla_none_retorna_fallback(self):
        """Si regla_json es None, retorna (0, True)"""
        self.assertEqual(
            CatalogRuleEngine.evaluar_regla(self.nave, None),
            (0, True),
        )

    def test_evaluar_regla_vacia_retorna_fallback(self):
        """Si regla_json es dict vacío, retorna (0, True)"""
        self.assertEqual(
            CatalogRuleEngine.evaluar_regla(self.nave, {}),
            (0, True),
        )

    def test_evaluar_regla_condicion_menor_o_igual_cumplida(self):
        """eslora=25 con condicion <=50 retorna resultado de esa condicion"""
        regla = {
            "atributo": "eslora",
            "condiciones": [
                {
                    "operador": "<=",
                    "valor": 50,
                    "resultado_cantidad": 2,
                    "resultado_visible": True,
                },
            ],
            "fallback_cantidad": 0,
            "fallback_visible": False,
        }
        self.assertEqual(
            CatalogRuleEngine.evaluar_regla(self.nave, regla),
            (2, True),
        )

    def test_evaluar_regla_condicion_mayor_cumplida(self):
        """eslora=25 con condicion >50 NO se cumple, usa fallback"""
        regla = {
            "atributo": "eslora",
            "condiciones": [
                {
                    "operador": ">",
                    "valor": 50,
                    "resultado_cantidad": 4,
                    "resultado_visible": True,
                }
            ],
            "fallback_cantidad": 1,
            "fallback_visible": False,
        }
        self.assertEqual(
            CatalogRuleEngine.evaluar_regla(self.nave, regla),
            (1, False),
        )

    def test_evaluar_regla_multiples_condiciones_primera_que_cumple(self):
        """Con condiciones <=10, <=50, >50 — una nave de eslora=25 cae en <=50"""
        self.assertEqual(
            CatalogRuleEngine.evaluar_regla(self.nave, self.regla_semanal),
            (2, True),
        )

    def test_evaluar_regla_atributo_inexistente_retorna_fallback(self):
        """Si el atributo no existe en la nave, retorna fallback de la regla"""
        regla = {
            "atributo": "atributo_que_no_existe",
            "condiciones": [
                {
                    "operador": "<=",
                    "valor": 99,
                    "resultado_cantidad": 10,
                    "resultado_visible": True,
                }
            ],
            "fallback_cantidad": 7,
            "fallback_visible": True,
        }
        self.assertEqual(
            CatalogRuleEngine.evaluar_regla(self.nave, regla),
            (7, True),
        )

    def test_evaluar_regla_fallback_personalizado(self):
        """fallback_cantidad y fallback_visible de la regla se respetan"""
        regla = {
            "atributo": "eslora",
            "condiciones": [
                {
                    "operador": ">",
                    "valor": 100,
                    "resultado_cantidad": 9,
                    "resultado_visible": True,
                }
            ],
            "fallback_cantidad": 5,
            "fallback_visible": False,
        }
        self.assertEqual(
            CatalogRuleEngine.evaluar_regla(self.nave, regla),
            (5, False),
        )

    def test_evaluar_regla_sin_version_se_trata_como_v1(self):
        """Filas viejas sin 'version' en el JSON siguen funcionando (retrocompatibilidad)."""
        self.assertEqual(
            CatalogRuleEngine.evaluar_regla(self.nave, self.regla_semanal),
            (2, True),
        )

    def test_evaluar_regla_version_1_explicita_se_evalua_igual(self):
        regla_v1 = {**self.regla_semanal, "version": 1}
        self.assertEqual(
            CatalogRuleEngine.evaluar_regla(self.nave, regla_v1),
            (2, True),
        )

    def test_evaluar_regla_version_desconocida_retorna_fallback_seguro(self):
        """Una versión que este motor no reconoce (ej. escrita por una versión futura
        de la app) no se interpreta a ciegas — cae al fallback seguro (0, True)."""
        regla_futura = {"version": 99, "algo": "que este motor no entiende"}
        self.assertEqual(
            CatalogRuleEngine.evaluar_regla(self.nave, regla_futura),
            (0, True),
        )


class TestConstruirLabelRequerimiento(TestCase):
    def test_tipo_estandar_usa_el_texto_del_editor(self):
        spec = {"id": "vigencia", "tipo": "estandar", "texto": "Vigencia mínima 6 meses"}
        self.assertEqual(construir_label_requerimiento(spec), "Vigencia mínima 6 meses")

    def test_tipo_condicion_es_fijo_sin_texto(self):
        spec = {"id": "condicion_1", "tipo": "condicion"}
        self.assertEqual(construir_label_requerimiento(spec), "Condición.")

    def test_tipo_cantidad_usa_el_valor_calculado_por_el_motor(self):
        spec = {"id": "__cantidad__", "tipo": "cantidad"}
        self.assertEqual(construir_label_requerimiento(spec, cantidad=4), "Cantidad: 4")

    def test_tipo_desconocido_cae_al_texto_por_compatibilidad_forward(self):
        spec = {"id": "futuro", "tipo": "algo_que_no_existe_aun", "texto": "texto de respaldo"}
        self.assertEqual(construir_label_requerimiento(spec), "texto de respaldo")


class TestRequerimientosEstandar(TestCase):
    def test_convierte_strings_planos_a_requerimientos_tipados(self):
        self.assertEqual(
            requerimientos_estandar("vigencia", "presión"),
            [
                {"id": "vigencia", "tipo": "estandar", "texto": "vigencia"},
                {"id": "presión", "tipo": "estandar", "texto": "presión"},
            ],
        )


class TestCatalogoVersion(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(nombre="Naviera V", rut="11111111-1", slug="naviera-v")
        self.nave = Nave.objects.create(
            naviera=self.naviera, nombre="Nave V", matricula="NVV-001",
            eslora=20.0, arqueo_bruto=200, capacidad_personas=10,
        )

    def test_primera_version_de_scope_es_numero_1(self):
        version = CatalogoVersion.crear_para_scope()
        self.assertEqual(version.numero, 1)
        self.assertIsNone(version.naviera)
        self.assertIsNone(version.nave)

    def test_versiones_secuenciales_mismo_scope(self):
        v1 = CatalogoVersion.crear_para_scope()
        v2 = CatalogoVersion.crear_para_scope()
        self.assertEqual((v1.numero, v2.numero), (1, 2))

    def test_secuencias_independientes_por_scope(self):
        central = CatalogoVersion.crear_para_scope()
        naviera_v = CatalogoVersion.crear_para_scope(naviera=self.naviera)
        self.assertEqual(central.numero, 1)
        self.assertEqual(naviera_v.numero, 1)

    def test_crear_para_scope_deriva_naviera_desde_nave(self):
        version = CatalogoVersion.crear_para_scope(nave=self.nave)
        self.assertEqual(version.naviera_id, self.naviera.id)

    def test_crear_para_scope_rechaza_naviera_nave_inconsistentes(self):
        otra_naviera = Naviera.objects.create(nombre="Otra", rut="22222222-2", slug="otra")
        with self.assertRaises(ValueError):
            CatalogoVersion.crear_para_scope(nave=self.nave, naviera=otra_naviera)

    @skipUnless(
        connection.features.supports_nulls_distinct_unique_constraints,
        "nulls_distinct=False solo se enforced a nivel de DB en backends que lo soportan (Postgres 15+); "
        "SQLite lo acepta pero no lo hace cumplir.",
    )
    def test_constraint_nulls_distinct_false_bloquea_numero_duplicado_central(self):
        CatalogoVersion.objects.create(naviera=None, nave=None, numero=1)
        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                CatalogoVersion.objects.create(naviera=None, nave=None, numero=1)


class TestCatalogoResolver(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(nombre="Naviera R", rut="33333333-3", slug="naviera-r")
        self.otra_naviera = Naviera.objects.create(nombre="Otra R", rut="44444444-4", slug="otra-r")
        self.nave = Nave.objects.create(
            naviera=self.naviera, nombre="Nave R", matricula="NVR-001",
            eslora=20.0, arqueo_bruto=200, capacidad_personas=10,
        )
        self.otra_nave_misma_naviera = Nave.objects.create(
            naviera=self.naviera, nombre="Nave R2", matricula="NVR-002",
            eslora=20.0, arqueo_bruto=200, capacidad_personas=10,
        )
        self.proposito = Proposito.objects.create(nombre="P", categoria="Seguridad", tipo="Material")
        self.periodicidad = Periodicidad.objects.create(nombre="Semanal", duracion_dias=7, offset_dias=1, responsabilidad="mar", visibilidad="todos")
        self.v_central = CatalogoVersion.crear_para_scope()

    def _recurso(self, nombre, *, naviera=None, nave=None, version=None, linaje_raiz=None, activo=True):
        return Recurso.objects.create(
            proposito=self.proposito, periodicidad=self.periodicidad, nombre=nombre,
            requerimientos=[], regla_aplicacion=None,
            naviera=naviera, nave=nave, catalogo_version=version or self.v_central,
            linaje_raiz=linaje_raiz, activo=activo,
        )

    def test_solo_central_sin_overrides(self):
        central = self._recurso("Extintor")
        efectivo = CatalogoResolver.catalogo_efectivo(self.nave)
        self.assertEqual([r.id for r in efectivo], [central.id])

    def test_override_naviera_reemplaza_central_para_todas_sus_naves(self):
        central = self._recurso("Extintor")
        v_naviera = CatalogoVersion.crear_para_scope(naviera=self.naviera)
        override = self._recurso("Extintor (override)", naviera=self.naviera, version=v_naviera, linaje_raiz=central)

        efectivo_nave1 = CatalogoResolver.catalogo_efectivo(self.nave)
        efectivo_nave2 = CatalogoResolver.catalogo_efectivo(self.otra_nave_misma_naviera)
        self.assertEqual([r.id for r in efectivo_nave1], [override.id])
        self.assertEqual([r.id for r in efectivo_nave2], [override.id])

    def test_override_naviera_no_afecta_otra_naviera(self):
        nave_otra_naviera = Nave.objects.create(
            naviera=self.otra_naviera, nombre="Nave Otra", matricula="NVO-001",
            eslora=20.0, arqueo_bruto=200, capacidad_personas=10,
        )
        central = self._recurso("Extintor")
        v_naviera = CatalogoVersion.crear_para_scope(naviera=self.naviera)
        self._recurso("Extintor (override)", naviera=self.naviera, version=v_naviera, linaje_raiz=central)

        efectivo = CatalogoResolver.catalogo_efectivo(nave_otra_naviera)
        self.assertEqual([r.id for r in efectivo], [central.id])

    def test_override_nave_gana_sobre_override_naviera_y_central(self):
        central = self._recurso("Extintor")
        v_naviera = CatalogoVersion.crear_para_scope(naviera=self.naviera)
        self._recurso("Extintor (naviera)", naviera=self.naviera, version=v_naviera, linaje_raiz=central)
        v_nave = CatalogoVersion.crear_para_scope(nave=self.nave)
        override_nave = self._recurso("Extintor (nave)", naviera=self.naviera, nave=self.nave, version=v_nave, linaje_raiz=central)

        efectivo = CatalogoResolver.catalogo_efectivo(self.nave)
        self.assertEqual([r.id for r in efectivo], [override_nave.id])

    def test_catalogo_independiente_en_nave_ignora_central(self):
        self._recurso("Extintor")
        self.nave.catalogo_independiente = True
        self.nave.save(update_fields=['catalogo_independiente'])

        efectivo = CatalogoResolver.catalogo_efectivo(self.nave)
        self.assertEqual(efectivo, [])

    def test_catalogo_independiente_en_naviera_se_hereda(self):
        self._recurso("Extintor")
        self.naviera.catalogo_independiente = True
        self.naviera.save(update_fields=['catalogo_independiente'])

        efectivo = CatalogoResolver.catalogo_efectivo(self.nave)
        self.assertEqual(efectivo, [])

    def test_recurso_independiente_nuevo_aparece_para_naves_de_su_naviera(self):
        propio = self._recurso("Equipo especial", naviera=self.naviera)
        efectivo = CatalogoResolver.catalogo_efectivo(self.nave)
        self.assertIn(propio.id, [r.id for r in efectivo])

    def test_activo_false_en_nave_no_filtra_a_central_oculta_la_lineage(self):
        central = self._recurso("Extintor")
        v_nave = CatalogoVersion.crear_para_scope(nave=self.nave)
        self._recurso("Extintor (removido)", naviera=self.naviera, nave=self.nave, version=v_nave, linaje_raiz=central, activo=False)

        efectivo = CatalogoResolver.catalogo_efectivo(self.nave)
        self.assertEqual(efectivo, [])
        efectivo_otra_nave = CatalogoResolver.catalogo_efectivo(self.otra_nave_misma_naviera)
        self.assertEqual([r.id for r in efectivo_otra_nave], [central.id])

    def test_activo_false_en_central_sin_override_oculta_en_todos_lados(self):
        self._recurso("Extintor", activo=False)
        efectivo = CatalogoResolver.catalogo_efectivo(self.nave)
        self.assertEqual(efectivo, [])

    def test_versiones_vigentes_naviera_sin_overrides_es_none(self):
        self._recurso("Extintor")
        versiones = CatalogoResolver.versiones_vigentes(self.nave)
        self.assertIsNotNone(versiones['central'])
        self.assertIsNone(versiones['naviera'])
        self.assertIsNone(versiones['nave'])

    def test_versiones_vigentes_naviera_independiente_central_es_none(self):
        self.naviera.catalogo_independiente = True
        self.naviera.save(update_fields=['catalogo_independiente'])
        versiones = CatalogoResolver.versiones_vigentes(self.nave)
        self.assertIsNone(versiones['central'])

    def test_pin_central_reconstruye_version_historica(self):
        v1_central = self._recurso("Extintor v1")
        v2 = CatalogoVersion.crear_para_scope()
        v2_central = self._recurso("Extintor v2", version=v2, linaje_raiz=v1_central)

        efectivo_v1 = CatalogoResolver.catalogo_efectivo(self.nave, pin_central=self.v_central.numero)
        efectivo_live = CatalogoResolver.catalogo_efectivo(self.nave)
        self.assertEqual([r.id for r in efectivo_v1], [v1_central.id])
        self.assertEqual([r.id for r in efectivo_live], [v2_central.id])


class TestCatalogoEditorService(TestCase):
    def setUp(self):
        self.proposito = Proposito.objects.create(nombre="P", categoria="Seguridad", tipo="Material")
        self.periodicidad = Periodicidad.objects.create(nombre="Semanal", duracion_dias=7, offset_dias=1, responsabilidad="mar", visibilidad="todos")

    def test_publicar_base_none_crea_raiz_nueva(self):
        version, filas = CatalogoEditorService.publicar(filas=[{
            'base': None,
            'cambios': {
                'proposito_id': self.proposito.id, 'periodicidad_id': self.periodicidad.id,
                'nombre': 'Extintor', 'requerimientos': [], 'regla_aplicacion': None,
            },
        }])
        self.assertEqual(version.numero, 1)
        self.assertIsNone(filas[0].linaje_raiz_id)

    def test_publicar_con_base_crea_nueva_version_en_misma_lineage(self):
        v1, (original,) = CatalogoEditorService.publicar(filas=[{
            'base': None,
            'cambios': {
                'proposito_id': self.proposito.id, 'periodicidad_id': self.periodicidad.id,
                'nombre': 'Extintor', 'requerimientos': [], 'regla_aplicacion': None,
            },
        }])
        v2, (editado,) = CatalogoEditorService.publicar(filas=[{'base': original, 'cambios': {'nombre': 'Extintor v2'}}])

        self.assertEqual(editado.raiz.id, original.id)
        self.assertEqual(editado.nombre, 'Extintor v2')
        original.refresh_from_db()
        self.assertEqual(original.nombre, 'Extintor')  # fila vieja intacta

    def test_publicar_override_naviera_desde_central(self):
        naviera = Naviera.objects.create(nombre="N", rut="55555555-5", slug="n")
        _, (central,) = CatalogoEditorService.publicar(filas=[{
            'base': None,
            'cambios': {
                'proposito_id': self.proposito.id, 'periodicidad_id': self.periodicidad.id,
                'nombre': 'Extintor', 'requerimientos': [], 'regla_aplicacion': None,
            },
        }])
        _, (override,) = CatalogoEditorService.publicar(
            naviera=naviera, filas=[{'base': central, 'cambios': {'nombre': 'Extintor (naviera)'}}],
        )
        self.assertEqual(override.naviera_id, naviera.id)
        self.assertEqual(override.raiz.id, central.id)

    def test_revertir_a_version_crea_version_nueva_sin_borrar_historia(self):
        base_cambios = {
            'proposito_id': self.proposito.id, 'periodicidad_id': self.periodicidad.id,
            'nombre': 'Extintor v1', 'requerimientos': [], 'regla_aplicacion': None,
        }
        v1, (r1,) = CatalogoEditorService.publicar(filas=[{'base': None, 'cambios': base_cambios}])
        v2, (r2,) = CatalogoEditorService.publicar(filas=[{'base': r1, 'cambios': {'nombre': 'Extintor v2'}}])
        v3, (r3,) = CatalogoEditorService.publicar(filas=[{'base': r2, 'cambios': {'nombre': 'Extintor v3'}}])

        conteo_antes = Recurso.objects.count()
        v4, (r4,) = CatalogoEditorService.revertir_a_version(numero_objetivo=v1.numero)

        self.assertEqual(v4.numero, 4)
        self.assertEqual(r4.nombre, 'Extintor v1')
        self.assertEqual(Recurso.objects.count(), conteo_antes + 1)
        for r in (r1, r2, r3):
            r.refresh_from_db()  # nada fue tocado
        self.assertEqual(r3.nombre, 'Extintor v3')

    def test_revertir_a_version_restaura_activo_false(self):
        base_cambios = {
            'proposito_id': self.proposito.id, 'periodicidad_id': self.periodicidad.id,
            'nombre': 'Extintor', 'requerimientos': [], 'regla_aplicacion': None,
        }
        v1, (r1,) = CatalogoEditorService.publicar(filas=[{'base': None, 'cambios': base_cambios}])
        v2, (r2,) = CatalogoEditorService.publicar(filas=[{'base': r1, 'cambios': {'activo': False}}])

        self.assertEqual(CatalogoResolver.catalogo_efectivo.__self__, CatalogoResolver)  # sanity import
        v3, (r3,) = CatalogoEditorService.revertir_a_version(numero_objetivo=v1.numero)
        self.assertTrue(r3.activo)
