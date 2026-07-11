from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from sitrep.accounts.models import AuditEvent, Naviera, Usuario
from sitrep.accounts.views import (
    _normalizar_rut,
    _pin_valido_4_digitos,
    _rut_valido,
    _normalizar_modo_login,
)


# ---------------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------------

class TestRutHelpers(TestCase):
    def test_rut_valido_formato_basico(self):
        self.assertTrue(_rut_valido("12345678-9"))

    def test_rut_valido_con_puntos(self):
        self.assertTrue(_rut_valido("12.345.678-9"))

    def test_rut_valido_verificador_k(self):
        self.assertTrue(_rut_valido("1234567-K"))

    def test_rut_invalido_sin_guion(self):
        self.assertFalse(_rut_valido("123456789"))

    def test_rut_invalido_vacio(self):
        self.assertFalse(_rut_valido(""))

    def test_rut_invalido_letras(self):
        self.assertFalse(_rut_valido("abc-k"))

    def test_normalizar_rut_elimina_puntos_y_espacios(self):
        self.assertEqual(_normalizar_rut("  12.345.678-9  "), "12345678-9")
        self.assertEqual(_normalizar_rut("12.345.678-K"), "12345678-K")


class TestPinHelpers(TestCase):
    def test_pin_valido_cuatro_digitos(self):
        self.assertTrue(_pin_valido_4_digitos("1234"))
        self.assertTrue(_pin_valido_4_digitos("0000"))

    def test_pin_invalido_vacio(self):
        self.assertFalse(_pin_valido_4_digitos(""))

    def test_pin_invalido_none(self):
        self.assertFalse(_pin_valido_4_digitos(None))

    def test_pin_invalido_menos_de_4(self):
        self.assertFalse(_pin_valido_4_digitos("123"))

    def test_pin_invalido_mas_de_4(self):
        self.assertFalse(_pin_valido_4_digitos("12345"))

    def test_pin_invalido_no_numerico(self):
        self.assertFalse(_pin_valido_4_digitos("abcd"))


class TestNormalizarModoLogin(TestCase):
    def test_modo_mar_retorna_mar(self):
        self.assertEqual(_normalizar_modo_login("mar"), "mar")

    def test_modo_tierra_retorna_tierra(self):
        self.assertEqual(_normalizar_modo_login("tierra"), "tierra")

    def test_modo_invalido_retorna_default_tierra(self):
        self.assertEqual(_normalizar_modo_login("otro"), "tierra")

    def test_modo_invalido_con_default_mar(self):
        self.assertEqual(_normalizar_modo_login("otro", modo_default="mar"), "mar")

    def test_modo_none_retorna_tierra(self):
        self.assertEqual(_normalizar_modo_login(None), "tierra")


# ---------------------------------------------------------------------------
# Vistas de gestión de usuarios
# ---------------------------------------------------------------------------

class TestCrearUsuario(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Test",
            rut="11111111-1",
            slug="test",
        )
        self.admin = Usuario.objects.create_user(
            username="admin_test",
            password="pass-seguro-123",
            naviera=self.naviera,
            rut="11111111-1",
            email="admin@test.com",
            rol="admin_naviera",
        )

    def _url(self):
        return reverse("inventory:crear_usuario", kwargs={"slug": self.naviera.slug})

    def test_crear_usuario_mar_exitoso(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(), {
            "rut": "22222222-2",
            "rol": "mar",
            "first_name": "Juan",
            "last_name": "Pérez",
            "pin": "1234",
        })
        self.assertRedirects(
            response,
            f"/{self.naviera.slug}/usuarios/",
            fetch_redirect_response=False,
        )
        self.assertTrue(Usuario.objects.filter(naviera=self.naviera, rut="22222222-2").exists())

    def test_crear_usuario_tierra_con_password(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(), {
            "rut": "33333333-3",
            "rol": "admin_naviera",
            "email": "nuevo@test.com",
            "password": "contrasena-segura-123",
        })
        self.assertRedirects(
            response,
            f"/{self.naviera.slug}/usuarios/",
            fetch_redirect_response=False,
        )
        self.assertTrue(Usuario.objects.filter(naviera=self.naviera, rut="33333333-3").exists())

    def test_rut_invalido_retorna_error_sin_crear(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(), {
            "rut": "RUT-INVALIDO",
            "rol": "mar",
            "pin": "1234",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "inválido")
        self.assertEqual(Usuario.objects.filter(naviera=self.naviera).count(), 1)

    def test_rut_duplicado_retorna_error(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(), {
            "rut": "11111111-1",
            "rol": "mar",
            "pin": "1234",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ya existe")

    def test_rol_mar_sin_pin_retorna_error(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(), {
            "rut": "22222222-2",
            "rol": "mar",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PIN")

    def test_rol_mar_pin_invalido_retorna_error(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(), {
            "rut": "22222222-2",
            "rol": "mar",
            "pin": "12",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "4 dígitos")

    def test_rol_tierra_sin_password_retorna_error(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(), {
            "rut": "22222222-2",
            "rol": "admin_naviera",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "contraseña")


class TestDesactivarUsuario(TestCase):
    def setUp(self):
        self.naviera_a = Naviera.objects.create(
            nombre="Naviera A", rut="11111111-1", slug="naviera-a"
        )
        self.naviera_b = Naviera.objects.create(
            nombre="Naviera B", rut="22222222-2", slug="naviera-b"
        )
        self.admin = Usuario.objects.create_user(
            username="admin_desact",
            password="pass-seguro-123",
            naviera=self.naviera_a,
            rut="11111111-1",
            email="admin@a.com",
            rol="admin_naviera",
        )
        self.marinero = Usuario.objects.create_user(
            username="marinero_desact",
            password="pass-seguro-123",
            naviera=self.naviera_a,
            rut="33333333-3",
            email="marinero@a.com",
            rol="mar",
        )
        self.usuario_b = Usuario.objects.create_user(
            username="usuario_b_desact",
            password="pass-seguro-123",
            naviera=self.naviera_b,
            rut="44444444-4",
            email="b@b.com",
            rol="mar",
        )

    def _url(self, naviera, usuario):
        return reverse(
            "inventory:desactivar_usuario",
            kwargs={"slug": naviera.slug, "id": usuario.id},
        )

    def test_desactivar_usuario_del_tenant(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(self.naviera_a, self.marinero))
        self.assertRedirects(
            response,
            f"/{self.naviera_a.slug}/usuarios/",
            fetch_redirect_response=False,
        )
        self.marinero.refresh_from_db()
        self.assertFalse(self.marinero.is_active)

    def test_no_puede_desactivarse_a_si_mismo(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(self.naviera_a, self.admin))
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_desactivar_usuario_de_otro_tenant_retorna_404(self):
        """naviera_a no puede desactivar usuario de naviera_b"""
        self.client.force_login(self.admin)
        url = reverse(
            "inventory:desactivar_usuario",
            kwargs={"slug": self.naviera_a.slug, "id": self.usuario_b.id},
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.usuario_b.refresh_from_db()
        self.assertTrue(self.usuario_b.is_active)


class TestCambiarPin(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Pin", rut="55555555-5", slug="naviera-pin"
        )
        self.admin = Usuario.objects.create_user(
            username="admin_pin",
            password="pass-seguro-123",
            naviera=self.naviera,
            rut="55555555-5",
            email="admin@pin.com",
            rol="admin_naviera",
        )
        self.marinero = Usuario.objects.create_user(
            username="marinero_pin",
            password="pass-seguro-123",
            naviera=self.naviera,
            rut="66666666-6",
            email="marinero@pin.com",
            rol="mar",
        )

    def _url(self, usuario):
        return reverse(
            "inventory:cambiar_pin",
            kwargs={"slug": self.naviera.slug, "id": usuario.id},
        )

    def test_cambiar_pin_exitoso(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(self.marinero), {"pin": "5678"})
        self.assertRedirects(
            response,
            f"/{self.naviera.slug}/usuarios/",
            fetch_redirect_response=False,
        )

    def test_pin_invalido_retorna_error(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._url(self.marinero), {"pin": "12"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "4 dígitos")

    def test_capitan_puede_cambiar_su_propio_pin(self):
        capitan = Usuario.objects.create_user(
            username="capitan_pin",
            password="pass-seguro-123",
            naviera=self.naviera,
            rut="77777777-7",
            email="capitan@pin.com",
            rol="capitan",
        )
        self.client.force_login(capitan)
        response = self.client.post(self._url(capitan), {"pin": "9999"})
        self.assertRedirects(
            response,
            f"/{self.naviera.slug}/usuarios/",
            fetch_redirect_response=False,
        )

    def test_capitan_no_puede_cambiar_pin_de_otro(self):
        capitan = Usuario.objects.create_user(
            username="capitan_pin2",
            password="pass-seguro-123",
            naviera=self.naviera,
            rut="88888888-8",
            email="capitan2@pin.com",
            rol="capitan",
        )
        self.client.force_login(capitan)
        response = self.client.post(self._url(self.marinero), {"pin": "9999"})
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# Softlock login mar/tierra (rol insuficiente no debe atrapar al usuario)
# ---------------------------------------------------------------------------

class TestSoftlockLoginRolInsuficiente(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Softlock", rut="44444444-4", slug="naviera-softlock"
        )
        self.marinero = Usuario.objects.create_user(
            username="marinero_softlock",
            password="pass-seguro-123",
            naviera=self.naviera,
            rut="99999999-9",
            email="marinero@softlock.com",
            rol="mar",
        )

    def test_mar_autenticado_en_login_sin_modo_va_a_kiosco_no_a_tierra(self):
        """Antes: modo_default='tierra' mandaba a un usuario mar a `/`, donde
        no tiene rol -> 403. El rol real del usuario manda sobre el modo."""
        self.client.force_login(self.marinero)
        response = self.client.get(
            reverse("inventory:login_tierra", kwargs={"slug": self.naviera.slug})
        )
        self.assertRedirects(
            response,
            f"/{self.naviera.slug}/kiosco/",
            fetch_redirect_response=False,
        )

    def test_rol_insuficiente_cierra_sesion_en_vez_de_atrapar_con_403(self):
        self.client.force_login(self.marinero)
        response = self.client.get(
            reverse("inventory:listar_usuarios", kwargs={"slug": self.naviera.slug})
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/{self.naviera.slug}/login/", response.url)
        self.assertNotIn("_auth_user_id", self.client.session)


# ---------------------------------------------------------------------------
# Audit trail y detección de anomalías
# ---------------------------------------------------------------------------

class TestAuditTrail(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Audit", rut="99999999-9", slug="audit-test"
        )
        self.admin = Usuario.objects.create_user(
            username="admin_audit",
            password="pass-seguro-123",
            naviera=self.naviera,
            rut="99999999-9",
            email="admin@audit.com",
            rol="admin_naviera",
        )

    def test_listar_usuarios_deja_audit_event(self):
        self.client.force_login(self.admin)
        self.client.get(reverse("inventory:listar_usuarios", kwargs={"slug": self.naviera.slug}))
        self.assertTrue(
            AuditEvent.objects.filter(usuario=self.admin, recurso="usuarios", accion="read").exists()
        )

    def test_usuario_anonimo_no_deja_audit_event(self):
        from sitrep.accounts.audit import registrar_acceso
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        registrar_acceso(request, "read", "usuarios")
        self.assertFalse(AuditEvent.objects.exists())


class TestDetectAnomalies(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Anom", rut="88888888-8", slug="anom-test"
        )
        self.usuario = Usuario.objects.create_user(
            username="lector_masivo",
            password="pass-seguro-123",
            naviera=self.naviera,
            rut="88888888-8",
            email="lector@anom.com",
            rol="tierra",
        )

    def _crear_eventos(self, cantidad):
        AuditEvent.objects.bulk_create([
            AuditEvent(
                usuario=self.usuario, naviera=self.naviera, rol="tierra",
                accion="read", recurso="usuarios",
            )
            for _ in range(cantidad)
        ])

    def test_bajo_umbral_no_reporta(self):
        self._crear_eventos(5)
        out = StringIO()
        call_command("detect_anomalies", "--threshold=50", stdout=out)
        self.assertIn("Sin anomalías", out.getvalue())

    def test_sobre_umbral_reporta(self):
        self._crear_eventos(51)
        out = StringIO()
        call_command("detect_anomalies", "--threshold=50", stdout=out)
        self.assertIn(f"usuario={self.usuario.id}", out.getvalue())


class TestTenantMemberRequired(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(nombre="Naviera Tenant", rut="12121212-1", slug="tenant-a")
        self.otra_naviera = Naviera.objects.create(nombre="Otra Tenant", rut="13131313-1", slug="tenant-b")
        self.admin_naviera = Usuario.objects.create_user(
            username="admin-naviera-tenant", naviera=self.naviera, rut="14141414-1",
            rol="admin_naviera", email="an@test.com",
        )
        self.admin_sitrep_global = Usuario.objects.create_user(
            username="admin-sitrep-global", naviera=None, rut="15151515-1",
            rol="admin_sitrep", is_superuser=True, email="asg@test.com",
        )

    def test_usuario_de_otra_naviera_es_rechazado(self):
        self.client.force_login(self.admin_naviera)
        resp = self.client.get(reverse("inventory:tenant_home", kwargs={"slug": self.otra_naviera.slug}))
        self.assertEqual(resp.status_code, 302)

    def test_admin_sitrep_sin_naviera_propia_entra_a_cualquier_tenant(self):
        self.client.force_login(self.admin_sitrep_global)
        resp = self.client.get(reverse("inventory:tenant_home", kwargs={"slug": self.naviera.slug}))
        self.assertEqual(resp.status_code, 200)
        resp_otra = self.client.get(reverse("inventory:tenant_home", kwargs={"slug": self.otra_naviera.slug}))
        self.assertEqual(resp_otra.status_code, 200)


class TestWebTenantBackendLogin(TestCase):
    """El login de tierra (email+password) pasa por WebTenantBackend, que
    tiene el mismo chequeo de naviera que tenant_member_required — un
    admin_sitrep global debe poder loguearse contra cualquier slug."""

    def setUp(self):
        self.naviera = Naviera.objects.create(nombre="Naviera Login", rut="16161616-1", slug="tenant-login")
        self.usuario_tenant = Usuario.objects.create_user(
            username="usuario-tenant-login", naviera=self.naviera, rut="17171717-1",
            rol="tierra", email="ut@test.com", password="clave-segura-1",
        )
        self.admin_sitrep_global = Usuario.objects.create_user(
            username="admin-sitrep-login", naviera=None, rut="18181818-1",
            rol="admin_sitrep", is_superuser=True, email="asl@test.com", password="clave-segura-2",
        )

    def _login(self, email, password):
        return self.client.post(
            reverse("inventory:login_tierra", kwargs={"slug": self.naviera.slug}),
            {"email": email, "password": password},
            follow=True,
        )

    def test_usuario_del_tenant_se_loguea_normal(self):
        resp = self._login("ut@test.com", "clave-segura-1")
        self.assertTrue(resp.wsgi_request.user.is_authenticated)

    def test_admin_sitrep_global_se_loguea_contra_cualquier_slug(self):
        resp = self._login("asl@test.com", "clave-segura-2")
        self.assertTrue(resp.wsgi_request.user.is_authenticated)
        self.assertEqual(resp.wsgi_request.user, self.admin_sitrep_global)
