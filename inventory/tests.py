from django.http import Http404
from django.test import TestCase
from django.urls import reverse

from .models import Dispositivo, Nave, Naviera, Usuario
from .services import TenantQueryService


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
