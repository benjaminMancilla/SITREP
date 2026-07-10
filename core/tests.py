from unittest.mock import patch

from django.test import TestCase, Client
from django.db import OperationalError

from core.forms import ArcoForm


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
