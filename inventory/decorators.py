# Thin shim — re-exports from accounts so existing imports keep working
from accounts.decorators import requiere_rol, tenant_member_required

__all__ = ["requiere_rol", "tenant_member_required"]
