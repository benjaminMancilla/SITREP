from django.core.cache import cache
from django.http import Http404
from django.test import TestCase
from django.urls import reverse

from sitrep.accounts.models import AuditEvent, Naviera, Usuario
from sitrep.fleet.models import Dispositivo, Nave
from sitrep.fleet.services import FleetQueryService


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


class TestFleetQueryService(TenantFixturesMixin, TestCase):
    def test_get_nave_de_otro_tenant_lanza_404(self):
        with self.assertRaises(Http404):
            FleetQueryService.get_nave(self.naviera_a, self.nave_b.id)

    def test_get_dispositivo_de_otro_tenant_lanza_404(self):
        with self.assertRaises(Http404):
            FleetQueryService.get_dispositivo(self.naviera_a, self.dispositivo_b.id)

    def test_get_nave_del_tenant_retorna_objeto(self):
        nave = FleetQueryService.get_nave(self.naviera_a, self.nave_a.id)
        self.assertEqual(nave.id, self.nave_a.id)


class TestBuscarDispositivoPorToken(TenantFixturesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.token_a = self.dispositivo_a.generar_nuevo_token()
        self.dispositivo_a.save()

    def test_token_valido_activo_retorna_dispositivo(self):
        d = FleetQueryService.buscar_dispositivo_por_token(self.naviera_a.id, self.token_a)
        self.assertEqual(d, self.dispositivo_a)

    def test_token_de_dispositivo_revocado_igual_retorna_dispositivo(self):
        """El match ignora is_active; el llamador decide rechazar."""
        self.dispositivo_a.is_active = False
        self.dispositivo_a.save()
        d = FleetQueryService.buscar_dispositivo_por_token(self.naviera_a.id, self.token_a)
        self.assertEqual(d, self.dispositivo_a)
        self.assertFalse(d.is_active)

    def test_token_incorrecto_retorna_none(self):
        self.assertIsNone(
            FleetQueryService.buscar_dispositivo_por_token(self.naviera_a.id, "token-que-no-existe")
        )

    def test_token_de_otra_naviera_retorna_none(self):
        """El token de naviera_a no valida contra naviera_b."""
        self.assertIsNone(
            FleetQueryService.buscar_dispositivo_por_token(self.naviera_b.id, self.token_a)
        )

    def test_sin_token_retorna_none(self):
        self.assertIsNone(FleetQueryService.buscar_dispositivo_por_token(self.naviera_a.id, ""))


class TestVerificarDispositivoEndpoint(TenantFixturesMixin, TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.token_a = self.dispositivo_a.generar_nuevo_token()
        self.dispositivo_a.save()
        self.url = f"/{self.naviera_a.slug}/api/v1/dispositivos/verificar/"

    def test_token_activo_valido_true(self):
        response = self.client.post(self.url, {"token": self.token_a}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["valido"])
        self.assertFalse(AuditEvent.objects.filter(recurso="dispositivo_token").exists())

    def test_token_revocado_valido_false_y_audita(self):
        self.dispositivo_a.is_active = False
        self.dispositivo_a.save()
        response = self.client.post(self.url, {"token": self.token_a}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["valido"])
        self.assertTrue(
            AuditEvent.objects.filter(recurso="dispositivo_token", accion="blocked").exists()
        )

    def test_sin_token_valido_false_sin_auditar(self):
        response = self.client.post(self.url, {}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["valido"])
        self.assertFalse(AuditEvent.objects.filter(recurso="dispositivo_token").exists())
