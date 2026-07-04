from django.test import TestCase

from sitrep.accounts.models import Naviera
from sitrep.fleet.models import Nave
from sitrep.catalog.services import CatalogRuleEngine


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
