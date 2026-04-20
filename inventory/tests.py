from django.http import Http404
from django.test import TestCase
from django.urls import reverse

from .models import (
    Dispositivo,
    MatrizNaveRecurso,
    Nave,
    Naviera,
    Periodicidad,
    Proposito,
    Recurso,
    Usuario,
)
from .services import MotorReglasSITREP, TenantQueryService


class TenantFixturesMixin:
    def setUp(self):
        self.naviera_a = Naviera.objects.create(
            nombre="Naviera A",
            rut="11111111-1",
            slug="tenant-a",
        )
        self.naviera_b = Naviera.objects.create(
            nombre="Naviera B",
            rut="22222222-2",
            slug="tenant-b",
        )

        self.nave_a = Nave.objects.create(
            naviera=self.naviera_a,
            nombre="Nave A",
            matricula="NVA-001",
            eslora=20.0,
            arqueo_bruto=200,
            capacidad_personas=15,
        )
        self.nave_b = Nave.objects.create(
            naviera=self.naviera_b,
            nombre="Nave B",
            matricula="NVB-001",
            eslora=30.0,
            arqueo_bruto=300,
            capacidad_personas=25,
        )

        self.dispositivo_a = Dispositivo.objects.create(
            naviera=self.naviera_a,
            nave=self.nave_a,
            nombre="Dispositivo A",
        )
        self.dispositivo_b = Dispositivo.objects.create(
            naviera=self.naviera_b,
            nave=self.nave_b,
            nombre="Dispositivo B",
        )

        self.admin_a = Usuario.objects.create_user(
            username="admin_a",
            password="password-seguro-123",
            naviera=self.naviera_a,
            rut="11111111-1",
            email="admin_a@example.com",
            rol="admin_naviera",
        )
        self.admin_b = Usuario.objects.create_user(
            username="admin_b",
            password="password-seguro-123",
            naviera=self.naviera_b,
            rut="22222222-2",
            email="admin_b@example.com",
            rol="admin_naviera",
        )


class TestIDORDispositivo(TenantFixturesMixin, TestCase):
    def test_revocar_dispositivo_de_otro_tenant_retorna_404(self):
        """naviera_a no puede revocar dispositivo_b"""
        self.client.force_login(self.admin_a)
        url = reverse(
            "inventory:revocar_dispositivo",
            kwargs={"slug": self.naviera_a.slug, "id": self.dispositivo_b.id},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)
        self.dispositivo_b.refresh_from_db()
        self.assertTrue(self.dispositivo_b.is_active)

    def test_listar_dispositivos_solo_muestra_los_del_tenant(self):
        """naviera_a solo ve sus propios dispositivos en el listado"""
        self.client.force_login(self.admin_a)
        url = reverse("inventory:listar_dispositivos", kwargs={"slug": self.naviera_a.slug})

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dispositivo A")
        self.assertNotContains(response, "Dispositivo B")


class TestIDORNave(TenantFixturesMixin, TestCase):
    def test_setup_kiosco_con_nave_de_otro_tenant_retorna_403(self):
        """naviera_a no puede asignar un dispositivo a nave_b"""
        self.client.force_login(self.admin_a)
        url = reverse("inventory:setup_kiosco", kwargs={"slug": self.naviera_a.slug})

        total_antes = Dispositivo.objects.count()
        response = self.client.post(
            url,
            {"nombre_dispositivo": "Intento IDOR", "nave_id": self.nave_b.id},
        )

        self.assertIn(response.status_code, [403, 404])
        self.assertEqual(Dispositivo.objects.count(), total_antes)


class TestTenantQueryService(TenantFixturesMixin, TestCase):
    def test_get_nave_de_otro_tenant_lanza_404(self):
        """TenantQueryService.get_nave con naviera incorrecta lanza Http404"""
        with self.assertRaises(Http404):
            TenantQueryService.get_nave(self.naviera_a, self.nave_b.id)

    def test_get_dispositivo_de_otro_tenant_lanza_404(self):
        """TenantQueryService.get_dispositivo con naviera incorrecta lanza Http404"""
        with self.assertRaises(Http404):
            TenantQueryService.get_dispositivo(self.naviera_a, self.dispositivo_b.id)

    def test_get_nave_del_tenant_retorna_objeto(self):
        nave = TenantQueryService.get_nave(self.naviera_a, self.nave_a.id)
        self.assertEqual(nave.id, self.nave_a.id)


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
        self.proposito = Proposito.objects.create(
            nombre="Seguridad Base",
            categoria="Seguridad",
            tipo="Material",
        )
        self.periodicidad = Periodicidad.objects.create(
            nombre="Semanal",
            duracion_dias=7,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
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

    def _crear_recurso(self, nombre, regla_aplicacion, naviera=None):
        return Recurso.objects.create(
            naviera=naviera,
            proposito=self.proposito,
            periodicidad=self.periodicidad,
            nombre=nombre,
            requerimientos=[],
            regla_aplicacion=regla_aplicacion,
        )

    def test_evaluar_regla_none_retorna_fallback(self):
        """Si regla_json es None, retorna (0, True)"""
        self.assertEqual(
            MotorReglasSITREP.evaluar_regla(self.nave, None),
            (0, True),
        )

    def test_evaluar_regla_vacia_retorna_fallback(self):
        """Si regla_json es dict vacío, retorna (0, True)"""
        self.assertEqual(
            MotorReglasSITREP.evaluar_regla(self.nave, {}),
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
            MotorReglasSITREP.evaluar_regla(self.nave, regla),
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
            MotorReglasSITREP.evaluar_regla(self.nave, regla),
            (1, False),
        )

    def test_evaluar_regla_multiples_condiciones_primera_que_cumple(self):
        """Con condiciones <=10, <=50, >50 — una nave de eslora=25 cae en <=50"""
        self.assertEqual(
            MotorReglasSITREP.evaluar_regla(self.nave, self.regla_semanal),
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
            MotorReglasSITREP.evaluar_regla(self.nave, regla),
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
            MotorReglasSITREP.evaluar_regla(self.nave, regla),
            (5, False),
        )

    def test_sincronizar_matriz_nave_crea_entradas(self):
        """Al sincronizar una nave con recursos aplicables, crea MatrizNaveRecurso"""
        recurso = self._crear_recurso(
            nombre="Extintor Global",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz = MatrizNaveRecurso.objects.get(nave=self.nave, recurso=recurso)
        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)
        self.assertFalse(matriz.modificado_manualmente)

    def test_sincronizar_matriz_nave_respeta_modificado_manualmente(self):
        """Una entrada con modificado_manualmente=True no es sobreescrita"""
        recurso = self._crear_recurso(
            nombre="Chaleco Global",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        matriz = MatrizNaveRecurso.objects.create(
            nave=self.nave,
            recurso=recurso,
            cantidad=99,
            es_visible=False,
            modificado_manualmente=True,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz.refresh_from_db()
        self.assertEqual(matriz.cantidad, 99)
        self.assertFalse(matriz.es_visible)
        self.assertTrue(matriz.modificado_manualmente)

    def test_sincronizar_matriz_nave_actualiza_entradas_existentes(self):
        """Una entrada existente sin modificado_manualmente=True sí se actualiza"""
        recurso = self._crear_recurso(
            nombre="Botiquin Global",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        matriz = MatrizNaveRecurso.objects.create(
            nave=self.nave,
            recurso=recurso,
            cantidad=1,
            es_visible=False,
            modificado_manualmente=False,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz.refresh_from_db()
        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_sincronizar_matriz_nave_catalogo_hibrido(self):
        """Recursos globales (naviera=None) y privados del tenant se incluyen"""
        recurso_global = self._crear_recurso(
            nombre="Recurso Global",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        recurso_privado = self._crear_recurso(
            nombre="Recurso Privado Tenant",
            regla_aplicacion=self.regla_semanal,
            naviera=self.naviera,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        recursos_en_matriz = set(
            MatrizNaveRecurso.objects.filter(nave=self.nave).values_list(
                "recurso_id",
                flat=True,
            )
        )
        self.assertEqual(recursos_en_matriz, {recurso_global.id, recurso_privado.id})

    def test_sincronizar_matriz_nave_excluye_recursos_de_otro_tenant(self):
        """Recursos privados de otra naviera no se incluyen en la matriz"""
        otra_naviera = Naviera.objects.create(
            nombre="Naviera Externa",
            rut="44444444-4",
            slug="naviera-externa",
        )
        recurso_global = self._crear_recurso(
            nombre="Recurso Global Incluido",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        recurso_privado_tenant = self._crear_recurso(
            nombre="Recurso Privado Incluido",
            regla_aplicacion=self.regla_semanal,
            naviera=self.naviera,
        )
        recurso_otro_tenant = self._crear_recurso(
            nombre="Recurso Privado Excluido",
            regla_aplicacion=self.regla_semanal,
            naviera=otra_naviera,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        self.assertTrue(
            MatrizNaveRecurso.objects.filter(
                nave=self.nave,
                recurso=recurso_global,
            ).exists()
        )
        self.assertTrue(
            MatrizNaveRecurso.objects.filter(
                nave=self.nave,
                recurso=recurso_privado_tenant,
            ).exists()
        )
        self.assertFalse(
            MatrizNaveRecurso.objects.filter(
                nave=self.nave,
                recurso=recurso_otro_tenant,
            ).exists()
        )
