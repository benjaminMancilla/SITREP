from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, Client, RequestFactory
from django.db import OperationalError
from django.urls import reverse

from core.forms import ArcoForm
from core.services import enviar_email_arco
from sitrep.accounts.models import AuditEvent, Naviera, Usuario


class HealthCheckDbTests(TestCase):
    def test_ok_when_db_reachable(self):
        response = Client().get("/health/db/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "reachable"})

    def test_503_and_no_leak_when_db_unreachable(self):
        with patch("django.db.connection.cursor", side_effect=OperationalError("password authentication failed for user secret")):
            response = Client().get("/health/db/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "error", "database": "unreachable"})
        self.assertNotIn("secret", response.content.decode())

    def test_not_cached(self):
        response = Client().get("/health/db/")
        self.assertIn("no-store", response.headers["Cache-Control"])


class ArcoFormTests(TestCase):
    def _valid_data(self, **overrides):
        data = {
            "nombre": "Juan Pérez",
            "rut": "12.345.678-9",
            "email": "juan@example.com",
            "empresa": "",
            "mensaje": "Quiero acceder a mis datos.",
            "pagina_web": "",
        }
        data.update(overrides)
        return data

    def test_valid_data_is_valid(self):
        form = ArcoForm(self._valid_data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_rut_is_invalid(self):
        form = ArcoForm(self._valid_data(rut=""))
        self.assertFalse(form.is_valid())
        self.assertIn("rut", form.errors)

    def test_honeypot_filled_is_spam(self):
        form = ArcoForm(self._valid_data(pagina_web="http://spam.example"))
        self.assertTrue(form.is_valid())
        self.assertTrue(form.is_spam())

    def test_empty_honeypot_is_not_spam(self):
        form = ArcoForm(self._valid_data())
        self.assertTrue(form.is_valid())
        self.assertFalse(form.is_spam())


class EnviarEmailArcoTests(TestCase):
    @patch("core.services.send_mail")
    def test_sends_to_arco_email_to(self, mock_send_mail):
        enviar_email_arco(
            nombre="Juan Pérez",
            rut="12.345.678-9",
            email="juan@example.com",
            empresa="",
            mensaje="Quiero acceder a mis datos.",
        )
        args, kwargs = mock_send_mail.call_args
        subject, body, from_email, to = args
        self.assertIn("ARCO", subject)
        self.assertIn("12.345.678-9", body)
        self.assertEqual(to, ["arco@sitrep.cl"])


class ArcoSolicitudViewTests(TestCase):
    def setUp(self):
        # El throttle usa el cache de Django, no se limpia solo entre tests.
        cache.clear()

    def _valid_data(self, **overrides):
        data = {
            "nombre": "Juan Pérez",
            "rut": "12.345.678-9",
            "email": "juan@example.com",
            "empresa": "",
            "mensaje": "Quiero acceder a mis datos.",
            "pagina_web": "",
            "pagina": "privacidad",
            "cf-turnstile-response": "test-token",
        }
        data.update(overrides)
        return data

    def test_legal_pages_expose_arco_form_in_context(self):
        response = Client().get(reverse("legal_privacidad"))
        self.assertIn("arco_form", response.context)
        self.assertEqual(response.context["legal_page_slug"], "privacidad")

    def test_invalid_pagina_falls_back_to_privacidad(self):
        response = Client().post(reverse("arco_solicitud"), self._valid_data(pagina="not-a-real-page"))
        self.assertRedirects(response, f"{reverse('legal_privacidad')}#arco", fetch_redirect_response=False)

    @patch("core.views.verify_turnstile", return_value=True)
    def test_honeypot_discards_without_sending_email(self, mock_verify):
        response = Client().post(reverse("arco_solicitud"), self._valid_data(pagina_web="http://spam.example"))
        self.assertRedirects(response, f"{reverse('legal_privacidad')}#arco", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)

    @patch("core.views.verify_turnstile", return_value=True)
    def test_valid_submission_sends_email_and_redirects_to_originating_page(self, mock_verify):
        response = Client().post(reverse("arco_solicitud"), self._valid_data(pagina="dpa"))
        self.assertRedirects(response, f"{reverse('legal_dpa')}#arco", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ARCO", mail.outbox[0].subject)

    @patch("core.views.verify_turnstile", return_value=False)
    def test_failed_turnstile_blocks_send(self, mock_verify):
        response = Client().post(reverse("arco_solicitud"), self._valid_data())
        self.assertRedirects(response, f"{reverse('legal_privacidad')}#arco", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)


class ApiRateThrottleRateSelectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def _request(self, method):
        request = getattr(self.factory, method.lower())("/fake/")
        request.user = AnonymousUser()
        return request

    def test_get_uses_read_rate(self):
        from core.throttling import ApiRateThrottle, READ_RATE

        throttle = ApiRateThrottle()
        throttle.allow_request(self._request("GET"), view=None)
        self.assertEqual(throttle.rate, READ_RATE)

    def test_post_uses_write_rate(self):
        from core.throttling import ApiRateThrottle, WRITE_RATE

        throttle = ApiRateThrottle()
        throttle.allow_request(self._request("POST"), view=None)
        self.assertEqual(throttle.rate, WRITE_RATE)

    def test_delete_uses_write_rate(self):
        from core.throttling import ApiRateThrottle, WRITE_RATE

        throttle = ApiRateThrottle()
        throttle.allow_request(self._request("DELETE"), view=None)
        self.assertEqual(throttle.rate, WRITE_RATE)

    def test_read_and_write_budgets_are_independent(self):
        from core.throttling import ApiRateThrottle, WRITE_RATE

        throttle = ApiRateThrottle()
        write_num_requests, _ = throttle.parse_rate(WRITE_RATE)

        # Enough GETs to exceed the WRITE threshold, but still far under the
        # READ budget (120/min) — this is the scenario a shared cache bucket
        # gets wrong: a burst of reads should never spend the write budget.
        for _ in range(write_num_requests + 1):
            self.assertTrue(throttle.allow_request(self._request("GET"), view=None))

        # The write budget must be untouched by all those reads.
        self.assertTrue(throttle.allow_request(self._request("POST"), view=None))


class ApiRateThrottleIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.naviera = Naviera.objects.create(
            nombre="Naviera Throttle", rut="22222222-2", slug="throttle-test",
        )
        self.user = Usuario.objects.create_user(
            username="tierra_throttle", password="pass-segura-123",
            naviera=self.naviera, rut="22222222-2", email="throttle@test.com",
            rol="tierra",
        )
        self.client.force_login(self.user)
        self.url = reverse("inventory:api_urgencia", kwargs={"slug": self.naviera.slug})

    @patch("core.throttling.READ_RATE", "2/min")
    @patch("core.api_base.report_security_incident")
    def test_exceeding_read_rate_returns_429_and_reports(self, mock_report):
        for _ in range(2):
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        mock_report.assert_called_once()
        self.assertEqual(mock_report.call_args.args[0], "rate_limit_exceeded")
        self.assertEqual(
            AuditEvent.objects.filter(
                accion="blocked", recurso="throttle", usuario=self.user,
            ).count(),
            1,
        )

    @patch("core.throttling.READ_RATE", "2/min")
    def test_requests_within_limit_are_not_blocked(self):
        for _ in range(2):
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(accion="blocked").count(), 0)
