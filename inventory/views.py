import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, login
from django.db import IntegrityError
from django.db.models import Count
from django.http import Http404, HttpResponse, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from .decorators import requiere_rol, tenant_member_required
from .models import Dispositivo, FichaRegistro, MatrizNaveRecurso, Nave, PeriodoRevision, Recurso, Tripulacion, Usuario
from .services import MotorFichas, TenantQueryService


def _pin_valido_4_digitos(raw_pin):
    return bool(raw_pin) and len(raw_pin) == 4 and raw_pin.isdigit()


ROLES_API_KIOSCO = {"mar", "capitan", "tierra", "admin_naviera", "admin_sitrep"}


def _json_error(mensaje, status):
    return JsonResponse({"error": mensaje}, status=status)


def _validar_rol_api_kiosco(request):
    if getattr(request.user, "rol", None) not in ROLES_API_KIOSCO:
        return _json_error("Acceso denegado: rango insuficiente.", 403)
    return None


def _obtener_nave_activa_desde_sesion(request):
    nave_id = request.session.get("nave_id")
    if not nave_id:
        return None, _json_error("Sesión de nave no disponible.", 403)

    try:
        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    except Http404:
        return None, _json_error("Nave no encontrada.", 404)

    return nave, None


def _obtener_periodo_de_nave(nave, periodo_id):
    try:
        return PeriodoRevision.objects.select_related("periodicidad").get(id=periodo_id, nave=nave)
    except PeriodoRevision.DoesNotExist:
        return None


def _extraer_payload_ficha_desde_json(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, _json_error("JSON inválido.", 400)

    if not isinstance(payload, dict):
        return None, _json_error("El body debe ser un objeto JSON.", 400)

    estado_operativo = payload.get("estado_operativo")
    observacion_general = payload.get("observacion_general", "")
    payload_checklist = payload.get("payload_checklist", {})

    if type(estado_operativo) is not bool:
        return None, _json_error("estado_operativo debe ser booleano.", 400)
    if not isinstance(observacion_general, str):
        return None, _json_error("observacion_general debe ser texto.", 400)
    if not isinstance(payload_checklist, dict):
        return None, _json_error("payload_checklist debe ser un objeto JSON.", 400)

    return {
        "estado_operativo": estado_operativo,
        "observacion_general": observacion_general,
        "payload_checklist": payload_checklist,
    }, None


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan", "tierra")
def dashboard_tierra(request, slug):
    naves_activas = TenantQueryService.get_naves_activas(request.naviera)
    total_usuarios = TenantQueryService.get_usuarios_del_tenant(request.naviera).count()
    total_dispositivos = Dispositivo.objects.filter(naviera=request.naviera, is_active=True).count()

    naves_resumen = []
    # TODO: optimizar con annotate() en Fase 4 para reducir queries por nave.
    for nave in naves_activas:
        periodos_abiertos = PeriodoRevision.objects.filter(nave=nave, estado="abierto").count()
        fichas_hoy = FichaRegistro.objects.filter(
            periodo__nave=nave,
            fecha_revision__date=timezone.localdate(),
        ).count()
        naves_resumen.append(
            {
                "nave": nave,
                "periodos_abiertos": periodos_abiertos,
                "fichas_hoy": fichas_hoy,
            }
        )

    return render(
        request,
        "inventory/dashboard_tierra.html",
        {
            "naves_resumen": naves_resumen,
            "total_usuarios": total_usuarios,
            "total_dispositivos": total_dispositivos,
            "slug": slug,
            "naviera": request.naviera,
        },
    )


def kiosco_home_placeholder(request, slug):
    return HttpResponse(f"Kiosco home placeholder para {slug}.", status=200)


def login_tierra(request, slug):
    tenant = getattr(request, "naviera", None)

    if request.user.is_authenticated and getattr(request.user, "naviera", None) == tenant:
        return redirect(f"/{slug}/")

    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        usuario = authenticate(request, email=email, password=password)
        if usuario is not None:
            login(request, usuario)
            return redirect(f"/{slug}/")

        return render(
            request,
            "inventory/login_tierra.html",
            {"error": "Credenciales inválidas."},
        )

    return render(request, "inventory/login_tierra.html")


def login_kiosco(request, slug):
    tenant = getattr(request, "naviera", None)

    if request.user.is_authenticated and getattr(request.user, "naviera", None) == tenant:
        return redirect(f"/{slug}/kiosco/")
    
    if request.method == "POST":
        rut = request.POST.get("rut")
        pin = request.POST.get("pin")
        dispositivo_token = request.POST.get("dispositivo_token")

        usuario = authenticate(
            request,
            rut=rut,
            pin=pin,
            naviera_id=getattr(request.naviera, "id", None),
            dispositivo_token=dispositivo_token,
        )
        if usuario is not None:
            dispositivo = getattr(usuario, "_dispositivo_autenticado", None)
            request.session["nave_id"] = getattr(dispositivo, "nave_id", None)
            login(request, usuario)
            return redirect(f"/{slug}/kiosco/")

        if getattr(request, "_dispositivo_revocado", False):
            return render(
                request,
                "inventory/login_kiosco.html",
                {"limpiar_token": True},
            )

        return render(
            request,
            "inventory/login_kiosco.html",
            {"error": "Acceso denegado."},
        )

    return render(request, "inventory/login_kiosco.html")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def setup_kiosco(request, slug):
    # 2. PROCESAMIENTO DEL PAYLOAD (POST)
    if request.method == "POST":
        nombre_dispositivo = request.POST.get("nombre_dispositivo")
        nave_id = request.POST.get("nave_id")

        if not nave_id:
            return HttpResponseForbidden("Debe asignar el dispositivo a una nave.")

        # Validación de Jurisdicción (Previene IDOR)
        nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)

        # Fabricación del Hardware Binding
        dispositivo = Dispositivo(naviera=request.naviera, nave=nave, nombre=nombre_dispositivo)
        token_plano = dispositivo.generar_nuevo_token()
        dispositivo.save()

        # Renderizamos la vista de éxito inyectando el token secreto
        contexto = {"token_plano": token_plano, "dispositivo": dispositivo}
        return render(request, "inventory/kiosco_tatuado.html", contexto)

    # 3. RENDERIZADO DEL FORMULARIO (GET)
    naves = TenantQueryService.get_naves_activas(request.naviera)
    return render(request, "inventory/kiosco_setup.html", {"naves": naves})


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def listar_dispositivos(request, slug):
    dispositivos = TenantQueryService.get_dispositivos(request.naviera).order_by("nave__nombre", "nombre")

    contexto = {
        "dispositivos": dispositivos,
        "slug": slug,
    }
    return render(request, "inventory/dispositivos_lista.html", contexto)


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def revocar_dispositivo(request, slug, id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    dispositivo = TenantQueryService.get_dispositivo(request.naviera, id)

    if not dispositivo.is_active:
        return redirect(f"/{slug}/kiosco/hardware/")

    dispositivo.is_active = False
    dispositivo.save(update_fields=["is_active"])

    return redirect(f"/{slug}/kiosco/hardware/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def listar_naves(request, slug):
    naves = TenantQueryService.get_naves_del_tenant(request.naviera)
    return render(
        request,
        "inventory/naves_lista.html",
        {
            "naves": naves,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def crear_nave(request, slug):
    if request.method == "GET":
        return render(
            request,
            "inventory/nave_form.html",
            {
                "slug": slug,
                "form_data": {},
            },
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    nombre = (request.POST.get("nombre") or "").strip()
    matricula = (request.POST.get("matricula") or "").strip()
    eslora = (request.POST.get("eslora") or "").strip()
    arqueo_bruto = (request.POST.get("arqueo_bruto") or "").strip()
    capacidad_personas = (request.POST.get("capacidad_personas") or "").strip()
    form_data = {
        "nombre": nombre,
        "matricula": matricula,
        "eslora": eslora,
        "arqueo_bruto": arqueo_bruto,
        "capacidad_personas": capacidad_personas,
    }

    if Nave.objects.filter(naviera=request.naviera, matricula=matricula, is_active=True).exists():
        return render(
            request,
            "inventory/nave_form.html",
            {
                "error": "La matrícula ya existe en esta naviera.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    try:
        Nave.objects.create(
            naviera=request.naviera,
            nombre=nombre,
            matricula=matricula,
            eslora=eslora,
            arqueo_bruto=arqueo_bruto,
            capacidad_personas=capacidad_personas,
        )
    except IntegrityError:
        return render(
            request,
            "inventory/nave_form.html",
            {
                "error": "La matrícula ya existe en esta naviera.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    return redirect(f"/{slug}/naves/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def editar_nave(request, slug, nave_id):
    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)

    if request.method == "GET":
        return render(
            request,
            "inventory/nave_form.html",
            {
                "slug": slug,
                "nave": nave,
                "editando": True,
                "form_data": {
                    "nombre": nave.nombre,
                    "matricula": nave.matricula,
                    "eslora": nave.eslora,
                    "arqueo_bruto": nave.arqueo_bruto,
                    "capacidad_personas": nave.capacidad_personas,
                },
            },
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    nombre = (request.POST.get("nombre") or "").strip()
    eslora_raw = (request.POST.get("eslora") or "").strip()
    arqueo_bruto_raw = (request.POST.get("arqueo_bruto") or "").strip()
    capacidad_personas_raw = (request.POST.get("capacidad_personas") or "").strip()
    form_data = {
        "nombre": nombre,
        "matricula": nave.matricula,
        "eslora": eslora_raw,
        "arqueo_bruto": arqueo_bruto_raw,
        "capacidad_personas": capacidad_personas_raw,
    }

    try:
        eslora = Decimal(eslora_raw)
        arqueo_bruto = int(arqueo_bruto_raw)
        capacidad_personas = int(capacidad_personas_raw)
    except (InvalidOperation, TypeError, ValueError):
        return render(
            request,
            "inventory/nave_form.html",
            {
                "error": "Eslora, arqueo bruto y capacidad deben ser numéricos válidos.",
                "slug": slug,
                "nave": nave,
                "editando": True,
                "form_data": form_data,
            },
        )

    nave.nombre = nombre
    nave.eslora = eslora
    nave.arqueo_bruto = arqueo_bruto
    nave.capacidad_personas = capacidad_personas
    nave.save(update_fields=["nombre", "eslora", "arqueo_bruto", "capacidad_personas"])

    return redirect(f"/{slug}/naves/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def desactivar_nave(request, slug, nave_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    nave = TenantQueryService.get_nave(request.naviera, nave_id)
    if not nave.is_active:
        return redirect(f"/{slug}/naves/")

    nave.delete()
    return redirect(f"/{slug}/naves/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def listar_usuarios(request, slug):
    usuarios = TenantQueryService.get_usuarios_del_tenant(request.naviera)
    return render(
        request,
        "inventory/usuarios_lista.html",
        {
            "usuarios": usuarios,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def crear_usuario(request, slug):
    if request.method == "GET":
        return render(
            request,
            "inventory/usuario_form.html",
            {
                "slug": slug,
                "form_data": {},
            },
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    rut = (request.POST.get("rut") or "").strip()
    email = (request.POST.get("email") or "").strip() or None
    rol = (request.POST.get("rol") or "").strip()
    first_name = (request.POST.get("first_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    raw_pin = (request.POST.get("pin") or "").strip()
    form_data = {
        "rut": rut,
        "email": email or "",
        "rol": rol,
        "first_name": first_name,
        "last_name": last_name,
    }

    if Usuario.objects.filter(naviera=request.naviera, rut=rut).exists():
        return render(
            request,
            "inventory/usuario_form.html",
            {
                "error": "El RUT ya existe en esta naviera.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    requiere_pin = rol in {"mar", "capitan"}
    if requiere_pin and not raw_pin:
        return render(
            request,
            "inventory/usuario_form.html",
            {
                "error": "El PIN es obligatorio para este rol.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    if requiere_pin and not _pin_valido_4_digitos(raw_pin):
        return render(
            request,
            "inventory/usuario_form.html",
            {
                "error": "El PIN debe ser de 4 dígitos numéricos.",
                "slug": slug,
                "form_data": form_data,
            },
        )

    usuario = Usuario(
        naviera=request.naviera,
        rut=rut,
        email=email,
        rol=rol,
        first_name=first_name,
        last_name=last_name,
    )

    if requiere_pin:
        usuario.set_pin(raw_pin)
        usuario.set_unusable_password()
    else:
        raw_password = (request.POST.get("password") or "").strip()
        if not raw_password:
            return render(
                request,
                "inventory/usuario_form.html",
                {
                    "error": "La contraseña es obligatoria para este rol.",
                    "slug": slug,
                    "form_data": form_data,
                },
            )
        usuario.set_password(raw_password)

    usuario.save()
    return redirect(f"/{slug}/usuarios/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera")
def desactivar_usuario(request, slug, id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    usuario = TenantQueryService.get_usuario_del_tenant(request.naviera, id)
    if request.user == usuario:
        return HttpResponseForbidden("No puedes desactivarte a ti mismo.")

    usuario.delete()
    return redirect(f"/{slug}/usuarios/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def cambiar_pin(request, slug, id):
    if request.user.rol == "capitan" and request.user.id != id:
        return HttpResponseForbidden("Acceso denegado.")

    usuario = TenantQueryService.get_usuario_activo_del_tenant(request.naviera, id)

    if request.method == "GET":
        return render(
            request,
            "inventory/cambiar_pin.html",
            {"usuario": usuario, "slug": slug},
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    raw_pin = (request.POST.get("pin") or "").strip()
    if not _pin_valido_4_digitos(raw_pin):
        return render(
            request,
            "inventory/cambiar_pin.html",
            {
                "usuario": usuario,
                "slug": slug,
                "error": "El PIN debe ser de 4 dígitos numéricos.",
            },
        )

    usuario.set_pin(raw_pin)
    usuario.save(update_fields=["pin_kiosco"])
    return redirect(f"/{slug}/usuarios/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def listar_tripulacion(request, slug, nave_id):
    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    tripulacion = TenantQueryService.get_tripulacion_activa_de_nave(request.naviera, nave_id)
    usuarios_asignados_ids = tripulacion.values_list("usuario_id", flat=True)
    usuarios_disponibles = TenantQueryService.get_usuarios_del_tenant(request.naviera).exclude(
        id__in=usuarios_asignados_ids
    )

    return render(
        request,
        "inventory/tripulacion_lista.html",
        {
            "nave": nave,
            "tripulacion": tripulacion,
            "usuarios_disponibles": usuarios_disponibles,
            "slug": slug,
        },
    )


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def agregar_tripulante(request, slug, nave_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)
    usuario_id = request.POST.get("usuario_id")
    usuario = TenantQueryService.get_usuario_activo_del_tenant(request.naviera, usuario_id)

    try:
        Tripulacion.objects.create(usuario=usuario, nave=nave)
    except IntegrityError:
        pass

    return redirect(f"/{slug}/naves/{nave_id}/tripulacion/")


@tenant_member_required
@requiere_rol("admin_sitrep", "admin_naviera", "capitan")
def remover_tripulante(request, slug, nave_id, tripulacion_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    nave = TenantQueryService.get_nave_activa(request.naviera, nave_id)

    try:
        tripulacion = Tripulacion.objects.get(id=tripulacion_id, nave=nave)
    except Tripulacion.DoesNotExist as exc:
        raise Http404("Recurso no encontrado.") from exc

    tripulacion.delete()
    return redirect(f"/{slug}/naves/{nave_id}/tripulacion/")


@tenant_member_required
def api_periodos_nave(request, slug):
    if request.method != "GET":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodos = list(TenantQueryService.get_periodos_abiertos_de_nave(nave).order_by("fecha_inicio", "id"))
    periodicidad_ids = [periodo.periodicidad_id for periodo in periodos]
    periodo_ids = [periodo.id for periodo in periodos]

    recursos_por_periodicidad = {}
    if periodicidad_ids:
        recursos_por_periodicidad = {
            row["recurso__periodicidad_id"]: row["total"]
            for row in (
                MatrizNaveRecurso.objects.filter(
                    nave=nave,
                    es_visible=True,
                    recurso__periodicidad_id__in=periodicidad_ids,
                )
                .values("recurso__periodicidad_id")
                .annotate(total=Count("id"))
            )
        }

    fichas_por_periodo = {}
    if periodo_ids:
        fichas_por_periodo = {
            row["periodo_id"]: row["total"]
            for row in (
                FichaRegistro.objects.filter(periodo_id__in=periodo_ids)
                .values("periodo_id")
                .annotate(total=Count("id"))
            )
        }

    payload = {
        "nave": {
            "id": nave.id,
            "nombre": nave.nombre,
            "matricula": nave.matricula,
        },
        "periodos": [
            {
                "id": periodo.id,
                "periodicidad": periodo.periodicidad.nombre,
                "fecha_inicio": periodo.fecha_inicio.isoformat(),
                "fecha_termino": periodo.fecha_termino.isoformat(),
                "estado": periodo.estado,
                "total_recursos": recursos_por_periodicidad.get(periodo.periodicidad_id, 0),
                "fichas_completadas": fichas_por_periodo.get(periodo.id, 0),
            }
            for periodo in periodos
        ],
    }
    return JsonResponse(payload, status=200)


@tenant_member_required
def api_recursos_periodo(request, slug, periodo_id):
    if request.method != "GET":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = _obtener_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    recursos = []
    matrices = TenantQueryService.get_recursos_visibles_de_nave_en_periodo(nave, periodo).order_by(
        "recurso__nombre",
        "id",
    )
    for matriz in matrices:
        ficha = TenantQueryService.get_ficha_de_periodo_y_recurso(periodo, matriz.recurso)
        recursos.append(
            {
                "matriz_id": matriz.id,
                "recurso_id": matriz.recurso_id,
                "nombre": matriz.recurso.nombre,
                "tipo": matriz.recurso.proposito.tipo,
                "categoria": matriz.recurso.proposito.categoria,
                "cantidad": matriz.cantidad,
                "requerimientos": matriz.recurso.requerimientos or [],
                "tiene_ficha": ficha is not None,
                "estado_operativo": ficha.estado_operativo if ficha else None,
                "observacion_general": ficha.observacion_general if ficha else "",
            }
        )

    payload = {
        "periodo": {
            "id": periodo.id,
            "periodicidad": periodo.periodicidad.nombre,
            "fecha_inicio": periodo.fecha_inicio.isoformat(),
            "fecha_termino": periodo.fecha_termino.isoformat(),
        },
        "recursos": recursos,
    }
    return JsonResponse(payload, status=200)


@tenant_member_required
def api_detalle_recurso(request, slug, periodo_id, recurso_id):
    if request.method != "GET":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = _obtener_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    try:
        matriz = MatrizNaveRecurso.objects.select_related(
            "recurso",
            "recurso__proposito",
            "recurso__periodicidad",
        ).get(
            nave=nave,
            recurso_id=recurso_id,
            es_visible=True,
            recurso__periodicidad_id=periodo.periodicidad_id,
        )
    except MatrizNaveRecurso.DoesNotExist:
        return _json_error("Recurso no encontrado en la matriz visible de la nave.", 404)

    ficha = TenantQueryService.get_ficha_de_periodo_y_recurso(periodo, matriz.recurso)
    usuario_ficha = None
    estado_operativo = None
    observacion_general = ""
    payload_checklist = {}
    fecha_revision = None

    if ficha:
        estado_operativo = ficha.estado_operativo
        observacion_general = ficha.observacion_general
        payload_checklist = ficha.payload_checklist or {}
        fecha_revision = ficha.fecha_revision.isoformat() if ficha.fecha_revision else None

        nombre_completo = f"{ficha.usuario.first_name} {ficha.usuario.last_name}".strip()
        if not nombre_completo:
            nombre_completo = ficha.usuario.rut
        usuario_ficha = f"{nombre_completo} ({ficha.usuario.rut})"

    payload = {
        "recurso": {
            "id": matriz.recurso.id,
            "nombre": matriz.recurso.nombre,
            "tipo": matriz.recurso.proposito.tipo,
            "categoria": matriz.recurso.proposito.categoria,
            "cantidad_requerida": matriz.cantidad,
            "requerimientos": matriz.recurso.requerimientos or [],
        },
        "ficha": {
            "existe": ficha is not None,
            "estado_operativo": estado_operativo,
            "observacion_general": observacion_general,
            "payload_checklist": payload_checklist,
            "fecha_revision": fecha_revision,
            "usuario": usuario_ficha,
        },
    }
    return JsonResponse(payload, status=200)


@tenant_member_required
def api_crear_ficha(request, slug, periodo_id, recurso_id):
    if request.method != "POST":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = _obtener_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    try:
        recurso = Recurso.objects.get(id=recurso_id)
    except Recurso.DoesNotExist:
        return _json_error("Recurso no encontrado.", 404)

    data, error = _extraer_payload_ficha_desde_json(request)
    if error:
        return error

    try:
        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=request.user,
            estado_operativo=data["estado_operativo"],
            observacion_general=data["observacion_general"],
            payload_checklist=data["payload_checklist"],
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    return JsonResponse({"id": ficha.id, "created": True}, status=201)


@tenant_member_required
def api_modificar_ficha(request, slug, periodo_id, recurso_id):
    if request.method != "PATCH":
        return _json_error("Método no permitido.", 405)

    error = _validar_rol_api_kiosco(request)
    if error:
        return error

    nave, error = _obtener_nave_activa_desde_sesion(request)
    if error:
        return error

    periodo = _obtener_periodo_de_nave(nave, periodo_id)
    if periodo is None:
        return _json_error("Período no encontrado.", 404)

    try:
        ficha = FichaRegistro.objects.get(periodo=periodo, recurso_id=recurso_id)
    except FichaRegistro.DoesNotExist:
        return _json_error("Ficha no encontrada para este recurso y período.", 404)

    data, error = _extraer_payload_ficha_desde_json(request)
    if error:
        return error

    try:
        ficha = MotorFichas.modificar_ficha(
            ficha=ficha,
            usuario_modificador=request.user,
            estado_operativo=data["estado_operativo"],
            observacion_general=data["observacion_general"],
            payload_checklist=data["payload_checklist"],
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    return JsonResponse({"id": ficha.id, "modified": True}, status=200)
