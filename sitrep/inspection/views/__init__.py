from sitrep.fleet.views import (  # noqa: F401
    listar_naves, crear_nave, editar_nave, desactivar_nave,
    listar_dispositivos, setup_kiosco, revocar_dispositivo,
    listar_tripulacion, agregar_tripulante, remover_tripulante,
)
from sitrep.accounts.views import (  # noqa: F401
    login_unificado, logout_kiosco, logout_tierra, redirect_kiosco_login,
    listar_usuarios, crear_usuario, desactivar_usuario, cambiar_pin,
)
from .tierra import dashboard_tierra, fallos_activos, periodos_vencidos, nave_detalle  # noqa: F401
from .kiosco import (  # noqa: F401
    dashboard_kiosco, kiosco_periodo_detalle, kiosco_periodo_pdf,
    kiosco_periodo_historial, kiosco_recurso_ficha,
)
from .api import (  # noqa: F401
    api_periodos_nave, api_recursos_periodo, api_detalle_recurso,
    api_crear_ficha, api_modificar_ficha, api_guardar_fichas_periodo,
)
