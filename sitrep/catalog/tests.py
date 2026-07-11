from django.db import IntegrityError, transaction as db_transaction
from django.test import TestCase

from sitrep.accounts.models import Naviera
from sitrep.fleet.models import Nave
from sitrep.catalog.models import CatalogoVersion
from sitrep.catalog.services import (
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

    def test_constraint_nulls_distinct_false_bloquea_numero_duplicado_central(self):
        CatalogoVersion.objects.create(naviera=None, nave=None, numero=1)
        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                CatalogoVersion.objects.create(naviera=None, nave=None, numero=1)
