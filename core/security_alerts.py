"""
Reporte de incidentes de seguridad a Sentry, separado de los errores 500.

Un evento reportado acá lleva tags/fingerprint propios (event_type=security_incident)
para que en Sentry se pueda armar una Alert Rule que filtre por ese tag y notifique
por un canal distinto al de "nuevo error" (ver docstring de report_security_incident).
"""
import sentry_sdk

from core.utils import get_client_ip


def report_security_incident(category, request=None, level="warning", **extra):
    """
    category: slug corto, ej. "exfiltration", "scan_burst", "unauthorized_access".
    level: "warning" (a revisar) o "fatal" (page inmediato).
    extra: pares clave/valor NO sensibles (conteos, ids, nombres de endpoint).
           No pasar objetos de modelo completos ni campos con PII cruda.
    """
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("event_type", "security_incident")
        scope.set_tag("security_category", category)
        scope.fingerprint = ["security-incident", category]

        context = dict(extra)
        if request is not None:
            user = getattr(request, "user", None)
            naviera = getattr(request, "naviera", None)
            session = getattr(request, "session", None)
            context.update({
                "usuario_id": getattr(user, "id", None),
                "rol": getattr(user, "rol", None),
                "naviera_slug": getattr(naviera, "slug", None),
                "ip": get_client_ip(request),
                "session_key": session.session_key if session else None,
                "path": request.path,
            })

        scope.set_context("security_incident", context)
        sentry_sdk.capture_message(f"[SECURITY] {category}", level=level)
