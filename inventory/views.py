from django.shortcuts import render
from django.http import HttpResponse

def dashboard_view(request):
    return render(request, 'dashboard.html')

def ping_view(request):
    return HttpResponse("<span class='text-emerald-400 font-mono'>Señal recibida. Conexión HTMX exitosa.</span>")