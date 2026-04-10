from django.shortcuts import render
from django.http import HttpResponseForbidden
from .models import Nave, Dispositivo
from .decorators import tenant_member_required, requiere_rol

@tenant_member_required
@requiere_rol('admin_sitrep', 'admin_naviera', 'capitan')
def setup_kiosco(request, slug):
    naviera = request.naviera

    # 2. PROCESAMIENTO DEL PAYLOAD (POST)
    if request.method == 'POST':
        nombre_dispositivo = request.POST.get('nombre_dispositivo')
        nave_id = request.POST.get('nave_id')

        # Validación de Jurisdicción (Previene IDOR)
        nave = None
        if nave_id:
            try:
                nave = Nave.objects.get(id=nave_id, naviera=naviera)
            except Nave.DoesNotExist:
                return HttpResponseForbidden("Intento de Brecha: La nave solicitada no pertenece a su tenant.")

        # Fabricación del Hardware Binding
        dispositivo = Dispositivo(
            naviera=naviera,
            nave=nave,
            nombre=nombre_dispositivo
        )
        token_plano = dispositivo.generar_nuevo_token()
        dispositivo.save()

        # Renderizamos la vista de éxito inyectando el token secreto
        contexto = {
            'token_plano': token_plano,
            'dispositivo': dispositivo
        }
        return render(request, 'inventory/kiosco_tatuado.html', contexto)

    # 3. RENDERIZADO DEL FORMULARIO (GET)
    naves = Nave.objects.filter(naviera=naviera, is_active=True)
    return render(request, 'inventory/kiosco_setup.html', {'naves': naves})
