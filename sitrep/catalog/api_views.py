from django.db import IntegrityError
from rest_framework.response import Response

from core.api_base import TierraAPIView
from core.permissions import PuedeEditarCatalogo
from sitrep.accounts.models import Naviera
from sitrep.fleet.models import Nave

from .models import Recurso
from .serializers import (
    CatalogoVersionSerializer, PublicarSerializer, RecursoSerializer, RevertirSerializer,
)
from .services import CatalogoEditorService, CatalogoResolver


def _resolver_naviera_y_nave(naviera_id, nave_id):
    """Resuelve (naviera, nave) desde ids sueltos y valida que sean
    consistentes entre sí — nave.naviera debe coincidir con naviera_id
    cuando ambos vienen (deuda documentada: CatalogoEditorService.publicar
    no lo valida, le corresponde a esta capa)."""
    nave = Nave.objects.select_related("naviera").get(pk=nave_id) if nave_id else None
    naviera = Naviera.objects.get(pk=naviera_id) if naviera_id else None
    if nave is not None:
        if naviera is not None and nave.naviera_id != naviera.id:
            raise ValueError("nave.naviera no coincide con naviera_id dada.")
        naviera = naviera or nave.naviera
    return naviera, nave


class CatalogoEfectivoView(TierraAPIView):
    """GET: catálogo vigente (sin pin_*) o histórico (con pin_*) para una nave,
    más las versiones vigentes por capa (para saber qué número usar en
    pin_*/revertir)."""
    audit_resource = "catalogo"

    def get(self, request, slug):
        nave_id = request.query_params.get("nave_id")
        if not nave_id:
            return Response({"error": "nave_id es requerido"}, status=400)
        try:
            nave = Nave.objects.select_related("naviera").get(pk=nave_id)
        except Nave.DoesNotExist:
            return Response({"error": "Nave no encontrada"}, status=404)

        def _pin(nombre):
            valor = request.query_params.get(nombre)
            return int(valor) if valor else None

        recursos = CatalogoResolver.catalogo_efectivo(
            nave,
            pin_central=_pin("pin_central"),
            pin_naviera=_pin("pin_naviera"),
            pin_nave=_pin("pin_nave"),
        )
        versiones = CatalogoResolver.versiones_vigentes(nave)
        return Response({
            "recursos": RecursoSerializer(recursos, many=True).data,
            "versiones_vigentes": {
                capa: (CatalogoVersionSerializer(version).data if version else None)
                for capa, version in versiones.items()
            },
        })


class RecursoPublicarView(TierraAPIView):
    """POST: crea, modifica (fork) o quita (soft-delete, cambios={'activo':
    False}) recursos del catálogo. Las tres operaciones son la misma llamada
    de negocio (CatalogoEditorService.publicar) con distinto payload."""
    permission_classes = [PuedeEditarCatalogo]
    audit_resource = "catalogo"
    audit_accion = "write"

    def post(self, request, slug):
        serializer = PublicarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = serializer.validated_data

        try:
            naviera, nave = _resolver_naviera_y_nave(datos["naviera_id"], datos["nave_id"])
        except (Naviera.DoesNotExist, Nave.DoesNotExist):
            return Response({"error": "naviera_id o nave_id no existen"}, status=404)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        filas = [
            {"base": fila["base"], "cambios": fila["cambios"]}
            for fila in datos["filas"]
        ]
        try:
            version, creadas = CatalogoEditorService.publicar(
                naviera=naviera, nave=nave, creado_por=request.user,
                nota=datos["nota"], filas=filas,
            )
        except IntegrityError as e:
            return Response({"error": f"Datos inválidos: {e}"}, status=400)

        return Response({
            "version": CatalogoVersionSerializer(version).data,
            "recursos": RecursoSerializer(creadas, many=True).data,
        }, status=201)


def _recursos_centrales_efectivos():
    """El 'catálogo padre' de una naviera es el central efectivo — mismo
    cálculo que la capa central dentro de CatalogoResolver.catalogo_efectivo,
    pero sin necesitar una nave."""
    central_qs = Recurso.objects.filter(naviera__isnull=True, nave__isnull=True)
    filas = CatalogoResolver.filas_vigentes_por_lineage(central_qs)
    return [fila for fila in filas.values() if fila is not None]


class CatalogoIndependienteView(TierraAPIView):
    """POST: marca o desmarca catalogo_independiente en una naviera o una
    nave. Desmarcarlo no borra recursos — solo hace que la capa central
    vuelva a entrar como fallback. Al marcarlo, copiar_desde_padre=True
    siembra el nuevo catálogo independiente con el efectivo de su padre
    (central para una naviera, central+naviera para una nave) en vez de
    dejarlo vacío — cada copia es un fork lineage-linked al original (igual
    que cualquier override), así que si más adelante se desmarca
    independiente no aparecen duplicados."""
    permission_classes = [PuedeEditarCatalogo]
    audit_resource = "catalogo"
    audit_accion = "write"

    def post(self, request, slug):
        naviera_id = request.data.get("naviera_id")
        nave_id = request.data.get("nave_id")
        independiente = bool(request.data.get("independiente", True))
        copiar_desde_padre = bool(request.data.get("copiar_desde_padre", False))
        if not naviera_id and not nave_id:
            return Response({"error": "naviera_id o nave_id es requerido"}, status=400)

        if nave_id:
            try:
                nave = Nave.objects.select_related("naviera").get(pk=nave_id)
            except Nave.DoesNotExist:
                return Response({"error": "Nave no encontrada"}, status=404)

            recursos_padre = CatalogoResolver.catalogo_efectivo(nave) if (independiente and copiar_desde_padre) else []
            nave.catalogo_independiente = independiente
            nave.save(update_fields=["catalogo_independiente"])
            creadas = self._copiar_desde_padre(naviera=nave.naviera, nave=nave, recursos_padre=recursos_padre, creado_por=request.user)
            return Response({
                "nave_id": nave.id, "catalogo_independiente": independiente,
                "recursos_copiados": len(creadas),
            })

        try:
            naviera = Naviera.objects.get(pk=naviera_id)
        except Naviera.DoesNotExist:
            return Response({"error": "Naviera no encontrada"}, status=404)

        recursos_padre = _recursos_centrales_efectivos() if (independiente and copiar_desde_padre) else []
        naviera.catalogo_independiente = independiente
        naviera.save(update_fields=["catalogo_independiente"])
        creadas = self._copiar_desde_padre(naviera=naviera, nave=None, recursos_padre=recursos_padre, creado_por=request.user)
        return Response({
            "naviera_id": naviera.id, "catalogo_independiente": independiente,
            "recursos_copiados": len(creadas),
        })

    @staticmethod
    def _copiar_desde_padre(*, naviera, nave, recursos_padre, creado_por):
        if not recursos_padre:
            return []
        _, creadas = CatalogoEditorService.publicar(
            naviera=naviera, nave=nave, creado_por=creado_por,
            nota="Copia inicial desde catálogo padre al independizar",
            filas=[{"base": r, "cambios": {}} for r in recursos_padre],
        )
        return creadas


class CatalogoRevertirView(TierraAPIView):
    """POST: vuelve el scope (naviera, nave) al estado que tenía en
    numero_objetivo — crea una nueva CatalogoVersion, nunca borra historia."""
    permission_classes = [PuedeEditarCatalogo]
    audit_resource = "catalogo"
    audit_accion = "write"

    def post(self, request, slug):
        serializer = RevertirSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = serializer.validated_data

        try:
            naviera, nave = _resolver_naviera_y_nave(datos["naviera_id"], datos["nave_id"])
        except (Naviera.DoesNotExist, Nave.DoesNotExist):
            return Response({"error": "naviera_id o nave_id no existen"}, status=404)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        version, filas = CatalogoEditorService.revertir_a_version(
            naviera=naviera, nave=nave, numero_objetivo=datos["numero_objetivo"],
            creado_por=request.user, nota=datos["nota"],
        )
        return Response({
            "version": CatalogoVersionSerializer(version).data,
            "recursos": RecursoSerializer(filas, many=True).data,
        }, status=201)
