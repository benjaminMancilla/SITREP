from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from .models import Nave, Dispositivo

@login_required
def setup_kiosco(request):
    usuario = request.user
    
    # 1. EL ESCUDO DE RANGOS: Un marinero raso no puede aprovisionar hardware
    if usuario.rol not in ['admin_sitrep', 'admin_naviera', 'capitan']:
        print(usuario.rol)
        return HttpResponseForbidden("Violación de Seguridad: Rango insuficiente para aprovisionar hardware.")

    # 2. PROCESAMIENTO DEL PAYLOAD (POST)
    if request.method == 'POST':
        nombre_dispositivo = request.POST.get('nombre_dispositivo')
        nave_id = request.POST.get('nave_id')

        # Validación de Jurisdicción (Previene IDOR)
        nave = None
        if nave_id:
            try:
                nave = Nave.objects.get(id=nave_id, naviera=usuario.naviera)
            except Nave.DoesNotExist:
                return HttpResponseForbidden("Intento de Brecha: La nave solicitada no pertenece a su tenant.")

        # Fabricación del Hardware Binding
        dispositivo = Dispositivo(
            naviera=usuario.naviera,
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
    naves = Nave.objects.filter(naviera=usuario.naviera, is_active=True)
    return render(request, 'inventory/kiosco_setup.html', {'naves': naves})