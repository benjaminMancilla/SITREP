from datetime import timedelta

from django.core.cache import cache
from django.http import Http404
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sitrep.accounts.models import AuditEvent, Naviera, Usuario
from sitrep.catalog.models import CatalogoVersion, Periodicidad, Recurso
from sitrep.fleet.api_views import FleetActividadView
from sitrep.fleet.models import Dispositivo, Nave
from sitrep.fleet.services import FleetQueryService
from sitrep.inspection.models import FichaRegistro, MatrizNaveRecurso, PeriodoRevision


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


class TestGetNavesConEstado(TenantFixturesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.periodicidad = Periodicidad.objects.create(
            nombre="Semanal",
            duracion_dias=7,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )
        self.catalogo_version = CatalogoVersion.crear_para_scope()
        self.recurso = Recurso.objects.create(
            categoria="Seguridad",
            tipo="Material",
            periodicidad=self.periodicidad,
            nombre="Extintor",
            requerimientos=[],
            regla_aplicacion={},
            catalogo_version=self.catalogo_version,
        )

    def test_resoluciones_matches_fallos_resueltos_predicate(self):
        """Mismo predicado que la tab Fallos resueltos: operativo ahora, con falla en el período anterior."""
        MatrizNaveRecurso.objects.create(
            nave=self.nave_a,
            recurso=self.recurso,
            cantidad=1,
            es_visible=True,
            ultimo_estado_operativo=True,
            ultimo_estado_operativo_anterior=False,
        )
        # no debe contar: sigue fallado
        recurso_b = Recurso.objects.create(
            categoria="Seguridad", tipo="Material", periodicidad=self.periodicidad,
            nombre="Chaleco", requerimientos=[], regla_aplicacion={},
            catalogo_version=self.catalogo_version,
        )
        MatrizNaveRecurso.objects.create(
            nave=self.nave_a,
            recurso=recurso_b,
            cantidad=1,
            es_visible=True,
            ultimo_estado_operativo=False,
            ultimo_estado_operativo_anterior=False,
        )

        nave = FleetQueryService.get_naves_con_estado(self.naviera_a).get(id=self.nave_a.id)

        self.assertEqual(nave.resoluciones, 1)
        self.assertEqual(nave.fallos_activos, 1)

    def test_ultima_ficha_en_uses_modificado_en_when_present(self):
        periodo = PeriodoRevision.objects.create(
            nave=self.nave_a,
            periodicidad=self.periodicidad,
            fecha_inicio=timezone.localdate(),
            fecha_termino=timezone.localdate(),
            estado="pendiente",
        )
        ficha = FichaRegistro.objects.create(
            periodo=periodo,
            recurso=self.recurso,
            usuario=self.admin_a,
            estado_operativo=True,
            payload_checklist={},
        )
        later = timezone.now() + timedelta(hours=2)
        ficha.modificado_en = later
        ficha.save(update_fields=["modificado_en"])

        nave = FleetQueryService.get_naves_con_estado(self.naviera_a).get(id=self.nave_a.id)

        self.assertEqual(nave.ultima_ficha_en, later)

    def test_ultima_ficha_en_none_when_no_fichas(self):
        nave = FleetQueryService.get_naves_con_estado(self.naviera_a).get(id=self.nave_a.id)

        self.assertIsNone(nave.ultima_ficha_en)

    def test_scoped_to_naviera(self):
        MatrizNaveRecurso.objects.create(
            nave=self.nave_b,
            recurso=self.recurso,
            cantidad=1,
            es_visible=True,
            ultimo_estado_operativo=False,
        )

        naves = FleetQueryService.get_naves_con_estado(self.naviera_a)

        self.assertEqual(list(naves.values_list("id", flat=True)), [self.nave_a.id])

    def test_fichas_hoy_cuenta_solo_las_de_hoy(self):
        recurso_b = Recurso.objects.create(
            categoria="Seguridad", tipo="Material", periodicidad=self.periodicidad,
            nombre="Chaleco fichas hoy", requerimientos=[], regla_aplicacion={},
            catalogo_version=self.catalogo_version,
        )
        periodo = PeriodoRevision.objects.create(
            nave=self.nave_a, periodicidad=self.periodicidad,
            fecha_inicio=timezone.localdate(), fecha_termino=timezone.localdate(),
            estado="pendiente",
        )
        FichaRegistro.objects.create(
            periodo=periodo, recurso=self.recurso, usuario=self.admin_a,
            estado_operativo=True, payload_checklist={},
        )
        ayer_ficha = FichaRegistro.objects.create(
            periodo=periodo, recurso=recurso_b, usuario=self.admin_a,
            estado_operativo=True, payload_checklist={},
        )
        FichaRegistro.objects.filter(id=ayer_ficha.id).update(
            fecha_revision=timezone.now() - timedelta(days=1)
        )

        nave = FleetQueryService.get_naves_con_estado(self.naviera_a).get(id=self.nave_a.id)

        self.assertEqual(nave.fichas_hoy, 1)


class TestNavesEstadoView(TenantFixturesMixin, TestCase):
    def test_lista_naves_con_estado_scoped_a_naviera(self):
        self.client.force_login(self.admin_a)
        url = reverse("inventory:api_naves_estado", kwargs={"slug": self.naviera_a.slug})

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.json()]
        self.assertEqual(ids, [self.nave_a.id])
        item = response.json()[0]
        self.assertEqual(item["nombre"], "Nave A")
        self.assertEqual(item["matricula"], "NVA-001")
        self.assertIn("resoluciones", item)
        self.assertIn("fichasHoy", item)
        self.assertIn("ultimaFichaEn", item)
        self.assertIsNone(item["ultimaFichaEn"])

    def test_mar_no_puede_acceder(self):
        mar = Usuario.objects.create_user(
            username="mar_a", password="password-seguro-123", naviera=self.naviera_a,
            rut="33333333-3", email="mar_a@example.com", rol="mar",
        )
        self.client.force_login(mar)
        url = reverse("inventory:api_naves_estado", kwargs={"slug": self.naviera_a.slug})

        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)


class TestGetActividadDiaria(TenantFixturesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.periodicidad = Periodicidad.objects.create(
            nombre="Semanal", duracion_dias=7, offset_dias=1,
            responsabilidad="mar", visibilidad="todos",
        )
        self.catalogo_version = CatalogoVersion.crear_para_scope()
        self.recurso = Recurso.objects.create(
            categoria="Seguridad", tipo="Material", periodicidad=self.periodicidad,
            nombre="Extintor", requerimientos=[], regla_aplicacion={},
            catalogo_version=self.catalogo_version,
        )

    def _crear_ficha(self, nave, fecha_revision):
        periodo = PeriodoRevision.objects.create(
            nave=nave, periodicidad=self.periodicidad,
            fecha_inicio=timezone.localdate(), fecha_termino=timezone.localdate(),
            estado="pendiente",
        )
        ficha = FichaRegistro.objects.create(
            periodo=periodo, recurso=self.recurso, usuario=self.admin_a,
            estado_operativo=True, payload_checklist={},
        )
        FichaRegistro.objects.filter(id=ficha.id).update(fecha_revision=fecha_revision)
        return ficha

    def test_ficha_cae_en_el_dia_correcto(self):
        hoy = timezone.now()
        self._crear_ficha(self.nave_a, hoy)

        inicio, conteos = FleetQueryService.get_actividad_diaria(self.naviera_a)

        self.assertEqual(conteos[self.nave_a.id][hoy.date()], 1)

    def test_scoped_a_naviera(self):
        hoy = timezone.now()
        self._crear_ficha(self.nave_b, hoy)

        inicio, conteos = FleetQueryService.get_actividad_diaria(self.naviera_a)

        self.assertNotIn(self.nave_b.id, conteos)

    def test_nave_ids_filtra_otras_naves(self):
        hoy = timezone.now()
        otra_nave = Nave.objects.create(
            naviera=self.naviera_a, nombre="Nave A2", matricula="NVA-002",
            eslora=20.0, arqueo_bruto=200, capacidad_personas=15,
        )
        self._crear_ficha(self.nave_a, hoy)
        self._crear_ficha(otra_nave, hoy)

        inicio, conteos = FleetQueryService.get_actividad_diaria(
            self.naviera_a, nave_ids=[self.nave_a.id]
        )

        self.assertIn(self.nave_a.id, conteos)
        self.assertNotIn(otra_nave.id, conteos)

    def test_ficha_fuera_de_ventana_se_excluye(self):
        vieja = timezone.now() - timedelta(days=100)
        self._crear_ficha(self.nave_a, vieja)

        inicio, conteos = FleetQueryService.get_actividad_diaria(self.naviera_a, dias=42)

        self.assertNotIn(self.nave_a.id, conteos)


class TestFleetActividadView(TenantFixturesMixin, TestCase):
    def test_scoped_a_naviera(self):
        self.client.force_login(self.admin_a)
        url = reverse("inventory:fleet_actividad", kwargs={"slug": self.naviera_a.slug})

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.json()]
        self.assertEqual(ids, [self.nave_a.id])

    def test_mar_no_puede_acceder(self):
        mar = Usuario.objects.create_user(
            username="mar_a", password="password-seguro-123", naviera=self.naviera_a,
            rut="33333333-3", email="mar_a@example.com", rol="mar",
        )
        self.client.force_login(mar)
        url = reverse("inventory:fleet_actividad", kwargs={"slug": self.naviera_a.slug})

        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)

    def test_respuesta_tiene_dias_densos_con_ceros(self):
        self.client.force_login(self.admin_a)
        url = reverse("inventory:fleet_actividad", kwargs={"slug": self.naviera_a.slug})

        response = self.client.get(url)

        item = response.json()[0]
        self.assertEqual(len(item["days"]), 42)
        self.assertTrue(all(d["count"] == 0 for d in item["days"]))
        self.assertIn("nombre", item)
        self.assertIn("matricula", item)

    def test_semanas_query_param_cambia_la_ventana(self):
        self.client.force_login(self.admin_a)
        url = reverse("inventory:fleet_actividad", kwargs={"slug": self.naviera_a.slug})

        response = self.client.get(url, {"semanas": 12})

        item = response.json()[0]
        self.assertEqual(len(item["days"]), 84)

    def test_semanas_fuera_de_rango_se_acota(self):
        self.client.force_login(self.admin_a)
        url = reverse("inventory:fleet_actividad", kwargs={"slug": self.naviera_a.slug})

        response = self.client.get(url, {"semanas": 999})

        item = response.json()[0]
        self.assertEqual(len(item["days"]), FleetActividadView.MAX_SEMANAS * 7)
