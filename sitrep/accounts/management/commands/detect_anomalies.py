"""
Detecta ráfagas de lectura/exportación de PII por usuario (posible exfiltración).
Pensado para correr por cron (ej. Railway Cron Jobs) cada pocos minutos.

# ponytail: agrupa por ventana fija sin estado persistido entre corridas —
# si una ráfaga dura más que la ventana, se re-alerta en la siguiente corrida
# (deseado). Si hace falta deduplicar alertas por ráfaga, agregar tabla de
# "incidentes abiertos" cuando el volumen de alertas se vuelva ruidoso.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from core.security_alerts import report_security_incident
from sitrep.accounts.models import AuditEvent

WINDOW_MINUTES = 5
THRESHOLD = 50


class Command(BaseCommand):
    help = "Reporta a Sentry usuarios cuyo volumen de lecturas/exportaciones de PII excede el umbral en la ventana."

    def add_arguments(self, parser):
        parser.add_argument("--window-minutes", type=int, default=WINDOW_MINUTES)
        parser.add_argument("--threshold", type=int, default=THRESHOLD)

    def handle(self, *args, **options):
        since = timezone.now() - timedelta(minutes=options["window_minutes"])
        ofensores = (
            AuditEvent.objects.filter(created_at__gte=since, accion__in=["read", "export"])
            .values("usuario_id", "naviera_id")
            .annotate(total=Count("id"))
            .filter(total__gte=options["threshold"])
        )

        if not ofensores:
            self.stdout.write("Sin anomalías.")
            return

        for fila in ofensores:
            report_security_incident(
                "exfiltration_suspected",
                level="fatal",
                usuario_id=fila["usuario_id"],
                naviera_id=fila["naviera_id"],
                eventos=fila["total"],
                ventana_minutos=options["window_minutes"],
            )
            self.stdout.write(self.style.WARNING(
                f"usuario={fila['usuario_id']} eventos={fila['total']} en {options['window_minutes']}min"
            ))
