from core.utils import get_client_ip


def registrar_acceso(request, accion, recurso, detalle=""):
    """Deja un AuditEvent. Usado tanto por vistas Django clásicas como por
    el hook de core.api_base para endpoints DRF — un solo lugar que escribe
    la tabla, para que el criterio de qué se guarda no diverja entre los dos."""
    if not getattr(request.user, "is_authenticated", False):
        return

    from .models import AuditEvent

    session = getattr(request, "session", None)
    AuditEvent.objects.create(
        usuario=request.user,
        naviera=getattr(request, "naviera", None),
        rol=getattr(request.user, "rol", ""),
        accion=accion,
        recurso=recurso,
        detalle=detalle,
        ip=get_client_ip(request),
        session_key=(session.session_key or "") if session else "",
        endpoint=request.path,
    )
