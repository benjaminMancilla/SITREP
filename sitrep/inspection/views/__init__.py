from sitrep.fleet.views import (  # noqa: F401
    listar_naves, crear_nave, editar_nave, desactivar_nave,
    listar_dispositivos, setup_kiosco, revocar_dispositivo,
    listar_tripulacion, agregar_tripulante, remover_tripulante,
)
from sitrep.accounts.views import (  # noqa: F401
    login_unificado, logout_kiosco, logout_tierra, redirect_kiosco_login,
    listar_usuarios, crear_usuario, desactivar_usuario, cambiar_pin,
)
from .tierra import (  # noqa: F401
    dashboard_tierra, fallos_activos, fallos_resueltos, fallos_feed,
    calendario, periodos_vencidos, nave_detalle, nave_periodo_detalle,
    nave_periodo_pdf,
)
from .kiosco import (  # noqa: F401
    dashboard_kiosco, kiosco_periodo_detalle, kiosco_periodo_pdf,
    kiosco_periodo_historial, kiosco_recurso_ficha,
)
from .api import api_guardar_fichas_periodo  # noqa: F401
