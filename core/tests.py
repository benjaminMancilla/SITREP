from unittest.mock import patch

from django.test import TestCase, Client
from django.db import OperationalError


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
