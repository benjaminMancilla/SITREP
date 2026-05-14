from datetime import date, datetime

from django.http import Http404
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from .models import (
    Area,
    Dispositivo,
    FichaRegistro,
    MatrizNaveRecurso,
    Nave,
    Naviera,
    Periodicidad,
    PeriodoRevision,
    Proposito,
    Recurso,
    Usuario,
)
from .services import MotorFichas, MotorPeriodos, MotorReglasSITREP, TenantQueryService


class TenantFixturesMixin:
    def setUp(self):
        self.naviera_a = Naviera.objects.create(
            nombre="Naviera A",
            rut="11111111-1",
            slug="tenant-a",
        )
        self.naviera_b = Naviera.objects.create(
            nombre="Naviera B",
            rut="22222222-2",
            slug="tenant-b",
        )

        self.nave_a = Nave.objects.create(
            naviera=self.naviera_a,
            nombre="Nave A",
            matricula="NVA-001",
            eslora=20.0,
            arqueo_bruto=200,
            capacidad_personas=15,
        )
        self.nave_b = Nave.objects.create(
            naviera=self.naviera_b,
            nombre="Nave B",
            matricula="NVB-001",
            eslora=30.0,
            arqueo_bruto=300,
            capacidad_personas=25,
        )

        self.dispositivo_a = Dispositivo.objects.create(
            naviera=self.naviera_a,
            nave=self.nave_a,
            nombre="Dispositivo A",
        )
        self.dispositivo_b = Dispositivo.objects.create(
            naviera=self.naviera_b,
            nave=self.nave_b,
            nombre="Dispositivo B",
        )

        self.admin_a = Usuario.objects.create_user(
            username="admin_a",
            password="password-seguro-123",
            naviera=self.naviera_a,
            rut="11111111-1",
            email="admin_a@example.com",
            rol="admin_naviera",
        )
        self.admin_b = Usuario.objects.create_user(
            username="admin_b",
            password="password-seguro-123",
            naviera=self.naviera_b,
            rut="22222222-2",
            email="admin_b@example.com",
            rol="admin_naviera",
        )


class TestIDORDispositivo(TenantFixturesMixin, TestCase):
    def test_revocar_dispositivo_de_otro_tenant_retorna_404(self):
        """naviera_a no puede revocar dispositivo_b"""
        self.client.force_login(self.admin_a)
        url = reverse(
            "inventory:revocar_dispositivo",
            kwargs={"slug": self.naviera_a.slug, "id": self.dispositivo_b.id},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)
        self.dispositivo_b.refresh_from_db()
        self.assertTrue(self.dispositivo_b.is_active)

    def test_listar_dispositivos_solo_muestra_los_del_tenant(self):
        """naviera_a solo ve sus propios dispositivos en el listado"""
        self.client.force_login(self.admin_a)
        url = reverse("inventory:listar_dispositivos", kwargs={"slug": self.naviera_a.slug})

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dispositivo A")
        self.assertNotContains(response, "Dispositivo B")


class TestIDORNave(TenantFixturesMixin, TestCase):
    def test_setup_kiosco_con_nave_de_otro_tenant_retorna_403(self):
        """naviera_a no puede asignar un dispositivo a nave_b"""
        self.client.force_login(self.admin_a)
        url = reverse("inventory:setup_kiosco", kwargs={"slug": self.naviera_a.slug})

        total_antes = Dispositivo.objects.count()
        response = self.client.post(
            url,
            {"nombre_dispositivo": "Intento IDOR", "nave_id": self.nave_b.id},
        )

        self.assertIn(response.status_code, [403, 404])
        self.assertEqual(Dispositivo.objects.count(), total_antes)


class TestTenantQueryService(TenantFixturesMixin, TestCase):
    def test_get_nave_de_otro_tenant_lanza_404(self):
        """TenantQueryService.get_nave con naviera incorrecta lanza Http404"""
        with self.assertRaises(Http404):
            TenantQueryService.get_nave(self.naviera_a, self.nave_b.id)

    def test_get_dispositivo_de_otro_tenant_lanza_404(self):
        """TenantQueryService.get_dispositivo con naviera incorrecta lanza Http404"""
        with self.assertRaises(Http404):
            TenantQueryService.get_dispositivo(self.naviera_a, self.dispositivo_b.id)

    def test_get_nave_del_tenant_retorna_objeto(self):
        nave = TenantQueryService.get_nave(self.naviera_a, self.nave_a.id)
        self.assertEqual(nave.id, self.nave_a.id)


class TestMotorReglasSITREP(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Motor",
            rut="33333333-3",
            slug="naviera-motor",
        )
        self.nave = Nave.objects.create(
            naviera=self.naviera,
            nombre="Nave Motor",
            matricula="NVM-001",
            eslora=25.0,
            arqueo_bruto=300,
            capacidad_personas=20,
        )
        self.proposito = Proposito.objects.create(
            nombre="Seguridad Base",
            categoria="Seguridad",
            tipo="Material",
        )
        self.periodicidad = Periodicidad.objects.create(
            nombre="Semanal",
            duracion_dias=7,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )
        self.regla_semanal = {
            "atributo": "eslora",
            "condiciones": [
                {
                    "operador": "<=",
                    "valor": 10,
                    "resultado_cantidad": 0,
                    "resultado_visible": False,
                },
                {
                    "operador": "<=",
                    "valor": 50,
                    "resultado_cantidad": 2,
                    "resultado_visible": True,
                },
                {
                    "operador": ">",
                    "valor": 50,
                    "resultado_cantidad": 4,
                    "resultado_visible": True,
                },
            ],
            "fallback_cantidad": 0,
            "fallback_visible": False,
        }

    def _crear_recurso(self, nombre, regla_aplicacion, naviera=None):
        return Recurso.objects.create(
            naviera=naviera,
            proposito=self.proposito,
            periodicidad=self.periodicidad,
            nombre=nombre,
            requerimientos=[],
            regla_aplicacion=regla_aplicacion,
        )

    def test_evaluar_regla_none_retorna_fallback(self):
        """Si regla_json es None, retorna (0, True)"""
        self.assertEqual(
            MotorReglasSITREP.evaluar_regla(self.nave, None),
            (0, True),
        )

    def test_evaluar_regla_vacia_retorna_fallback(self):
        """Si regla_json es dict vacío, retorna (0, True)"""
        self.assertEqual(
            MotorReglasSITREP.evaluar_regla(self.nave, {}),
            (0, True),
        )

    def test_evaluar_regla_condicion_menor_o_igual_cumplida(self):
        """eslora=25 con condicion <=50 retorna resultado de esa condicion"""
        regla = {
            "atributo": "eslora",
            "condiciones": [
                {
                    "operador": "<=",
                    "valor": 50,
                    "resultado_cantidad": 2,
                    "resultado_visible": True,
                },
            ],
            "fallback_cantidad": 0,
            "fallback_visible": False,
        }
        self.assertEqual(
            MotorReglasSITREP.evaluar_regla(self.nave, regla),
            (2, True),
        )

    def test_evaluar_regla_condicion_mayor_cumplida(self):
        """eslora=25 con condicion >50 NO se cumple, usa fallback"""
        regla = {
            "atributo": "eslora",
            "condiciones": [
                {
                    "operador": ">",
                    "valor": 50,
                    "resultado_cantidad": 4,
                    "resultado_visible": True,
                }
            ],
            "fallback_cantidad": 1,
            "fallback_visible": False,
        }
        self.assertEqual(
            MotorReglasSITREP.evaluar_regla(self.nave, regla),
            (1, False),
        )

    def test_evaluar_regla_multiples_condiciones_primera_que_cumple(self):
        """Con condiciones <=10, <=50, >50 — una nave de eslora=25 cae en <=50"""
        self.assertEqual(
            MotorReglasSITREP.evaluar_regla(self.nave, self.regla_semanal),
            (2, True),
        )

    def test_evaluar_regla_atributo_inexistente_retorna_fallback(self):
        """Si el atributo no existe en la nave, retorna fallback de la regla"""
        regla = {
            "atributo": "atributo_que_no_existe",
            "condiciones": [
                {
                    "operador": "<=",
                    "valor": 99,
                    "resultado_cantidad": 10,
                    "resultado_visible": True,
                }
            ],
            "fallback_cantidad": 7,
            "fallback_visible": True,
        }
        self.assertEqual(
            MotorReglasSITREP.evaluar_regla(self.nave, regla),
            (7, True),
        )

    def test_evaluar_regla_fallback_personalizado(self):
        """fallback_cantidad y fallback_visible de la regla se respetan"""
        regla = {
            "atributo": "eslora",
            "condiciones": [
                {
                    "operador": ">",
                    "valor": 100,
                    "resultado_cantidad": 9,
                    "resultado_visible": True,
                }
            ],
            "fallback_cantidad": 5,
            "fallback_visible": False,
        }
        self.assertEqual(
            MotorReglasSITREP.evaluar_regla(self.nave, regla),
            (5, False),
        )

    def test_sincronizar_matriz_nave_crea_entradas(self):
        """Al sincronizar una nave con recursos aplicables, crea MatrizNaveRecurso"""
        recurso = self._crear_recurso(
            nombre="Extintor Global",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz = MatrizNaveRecurso.objects.get(nave=self.nave, recurso=recurso)
        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)
        self.assertFalse(matriz.modificado_manualmente)

    def test_sincronizar_matriz_nave_respeta_modificado_manualmente(self):
        """Una entrada con modificado_manualmente=True no es sobreescrita"""
        recurso = self._crear_recurso(
            nombre="Chaleco Global",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        matriz = MatrizNaveRecurso.objects.create(
            nave=self.nave,
            recurso=recurso,
            cantidad=99,
            es_visible=False,
            modificado_manualmente=True,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz.refresh_from_db()
        self.assertEqual(matriz.cantidad, 99)
        self.assertFalse(matriz.es_visible)
        self.assertTrue(matriz.modificado_manualmente)

    def test_sincronizar_matriz_nave_actualiza_entradas_existentes(self):
        """Una entrada existente sin modificado_manualmente=True sí se actualiza"""
        recurso = self._crear_recurso(
            nombre="Botiquin Global",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        matriz = MatrizNaveRecurso.objects.create(
            nave=self.nave,
            recurso=recurso,
            cantidad=1,
            es_visible=False,
            modificado_manualmente=False,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        matriz.refresh_from_db()
        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_sincronizar_matriz_nave_catalogo_hibrido(self):
        """Recursos globales (naviera=None) y privados del tenant se incluyen"""
        recurso_global = self._crear_recurso(
            nombre="Recurso Global",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        recurso_privado = self._crear_recurso(
            nombre="Recurso Privado Tenant",
            regla_aplicacion=self.regla_semanal,
            naviera=self.naviera,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        recursos_en_matriz = set(
            MatrizNaveRecurso.objects.filter(nave=self.nave).values_list(
                "recurso_id",
                flat=True,
            )
        )
        self.assertEqual(recursos_en_matriz, {recurso_global.id, recurso_privado.id})

    def test_sincronizar_matriz_nave_excluye_recursos_de_otro_tenant(self):
        """Recursos privados de otra naviera no se incluyen en la matriz"""
        otra_naviera = Naviera.objects.create(
            nombre="Naviera Externa",
            rut="44444444-4",
            slug="naviera-externa",
        )
        recurso_global = self._crear_recurso(
            nombre="Recurso Global Incluido",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        recurso_privado_tenant = self._crear_recurso(
            nombre="Recurso Privado Incluido",
            regla_aplicacion=self.regla_semanal,
            naviera=self.naviera,
        )
        recurso_otro_tenant = self._crear_recurso(
            nombre="Recurso Privado Excluido",
            regla_aplicacion=self.regla_semanal,
            naviera=otra_naviera,
        )

        MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        self.assertTrue(
            MatrizNaveRecurso.objects.filter(
                nave=self.nave,
                recurso=recurso_global,
            ).exists()
        )
        self.assertTrue(
            MatrizNaveRecurso.objects.filter(
                nave=self.nave,
                recurso=recurso_privado_tenant,
            ).exists()
        )
        self.assertFalse(
            MatrizNaveRecurso.objects.filter(
                nave=self.nave,
                recurso=recurso_otro_tenant,
            ).exists()
        )

    def test_sincronizar_matriz_nave_retorna_estadisticas(self):
        """Retorna estadisticas de creados, actualizados, omitidos y errores"""
        recurso_creado = self._crear_recurso(
            nombre="Recurso Creado",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        recurso_actualizado = self._crear_recurso(
            nombre="Recurso Actualizado",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        recurso_omitido = self._crear_recurso(
            nombre="Recurso Omitido",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )

        MatrizNaveRecurso.objects.create(
            nave=self.nave,
            recurso=recurso_actualizado,
            cantidad=1,
            es_visible=False,
            modificado_manualmente=False,
        )
        MatrizNaveRecurso.objects.create(
            nave=self.nave,
            recurso=recurso_omitido,
            cantidad=99,
            es_visible=False,
            modificado_manualmente=True,
        )

        stats = MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        self.assertEqual(
            stats,
            {
                "recursos_creados": 1,
                "recursos_actualizados": 1,
                "recursos_omitidos": 1,
                "recursos_con_error": 0,
            },
        )
        self.assertTrue(
            MatrizNaveRecurso.objects.filter(nave=self.nave, recurso=recurso_creado).exists()
        )

    def test_sincronizar_matriz_nave_continua_si_un_recurso_falla(self):
        """Si un recurso falla, los demás recursos deben seguir procesándose"""
        recurso_ok = self._crear_recurso(
            nombre="Recurso OK",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )
        recurso_falla = self._crear_recurso(
            nombre="Recurso Falla",
            regla_aplicacion=self.regla_semanal,
            naviera=None,
        )

        original_get_or_create = MatrizNaveRecurso.objects.get_or_create

        def get_or_create_con_fallo(*args, **kwargs):
            if kwargs.get("recurso") == recurso_falla:
                raise RuntimeError("fallo simulado de recurso")
            return original_get_or_create(*args, **kwargs)

        with patch.object(
            MatrizNaveRecurso.objects,
            "get_or_create",
            side_effect=get_or_create_con_fallo,
        ):
            with self.assertLogs("inventory.services", level="ERROR") as logs:
                stats = MotorReglasSITREP.sincronizar_matriz_nave(self.nave)

        self.assertEqual(stats["recursos_con_error"], 1)
        self.assertEqual(stats["recursos_creados"], 1)
        self.assertEqual(stats["recursos_actualizados"], 0)
        self.assertEqual(stats["recursos_omitidos"], 0)
        self.assertTrue(
            MatrizNaveRecurso.objects.filter(nave=self.nave, recurso=recurso_ok).exists()
        )
        self.assertFalse(
            MatrizNaveRecurso.objects.filter(nave=self.nave, recurso=recurso_falla).exists()
        )
        self.assertTrue(any("Error processing recurso" in linea for linea in logs.output))


class TestMotorPeriodosEstados(TestCase):
    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Estados",
            rut="55555555-5",
            slug="naviera-estados",
        )
        self.periodicidad = Periodicidad.objects.create(
            nombre="Mensual",
            duracion_dias=30,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )
        self.proposito = Proposito.objects.create(
            nombre="Seguridad Operativa",
            categoria="Seguridad",
            tipo="Material",
        )
        self.recurso_a = Recurso.objects.create(
            naviera=None,
            proposito=self.proposito,
            periodicidad=self.periodicidad,
            nombre="Extintor A",
            requerimientos=["vigencia", "presion"],
            regla_aplicacion=None,
        )
        self.recurso_b = Recurso.objects.create(
            naviera=None,
            proposito=self.proposito,
            periodicidad=self.periodicidad,
            nombre="Extintor B",
            requerimientos=["sello"],
            regla_aplicacion=None,
        )
        self.recurso_sin_checklist = Recurso.objects.create(
            naviera=None,
            proposito=self.proposito,
            periodicidad=self.periodicidad,
            nombre="Radio VHF",
            requerimientos=[],
            regla_aplicacion=None,
        )
        self.usuario = Usuario.objects.create_user(
            username="marinero_estados",
            password="password-seguro-123",
            naviera=self.naviera,
            rut="55555555-6",
            email="marinero@example.com",
            rol="mar",
        )
        self.nave = Nave.objects.create(
            naviera=self.naviera,
            nombre="Nave Estados",
            matricula="NVE-001",
            eslora=20.0,
            arqueo_bruto=200,
            capacidad_personas=12,
        )
        self.periodo = PeriodoRevision.objects.get(
            nave=self.nave,
            periodicidad=self.periodicidad,
        )

    def _crear_ficha(self, recurso, estado_operativo, payload_checklist, observacion_general=""):
        return MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=estado_operativo,
            observacion_general=observacion_general,
            payload_checklist=payload_checklist,
        )

    def test_get_periodos_abiertos_de_nave_incluye_pendiente_y_en_proceso(self):
        otra_periodicidad = Periodicidad.objects.create(
            nombre="Semanal Estados",
            duracion_dias=7,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )
        periodo_en_proceso = PeriodoRevision.objects.create(
            nave=self.nave,
            periodicidad=otra_periodicidad,
            fecha_inicio=timezone.localdate(),
            fecha_termino=timezone.localdate(),
            estado="en_proceso",
        )
        PeriodoRevision.objects.create(
            nave=self.nave,
            periodicidad=otra_periodicidad,
            fecha_inicio=timezone.localdate(),
            fecha_termino=timezone.localdate(),
            estado="operativo",
        )

        periodos_ids = set(
            TenantQueryService.get_periodos_abiertos_de_nave(self.nave).values_list("id", flat=True)
        )

        self.assertIn(self.periodo.id, periodos_ids)
        self.assertIn(periodo_en_proceso.id, periodos_ids)
        self.assertEqual(len(periodos_ids), 2)

    def test_crear_ficha_parcial_mantiene_periodo_pendiente(self):
        ficha = self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=None,
            payload_checklist={"vigencia": {"cumple": True}},
        )

        self.periodo.refresh_from_db()

        self.assertIsNone(ficha.estado_operativo)
        self.assertEqual(self.periodo.estado, "pendiente")

    def test_crear_ficha_completa_cambia_periodo_a_en_proceso(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=True,
            payload_checklist={
                "vigencia": {"cumple": True},
                "presion": {"cumple": True},
            },
        )

        self.periodo.refresh_from_db()

        self.assertEqual(self.periodo.estado, "en_proceso")

    def test_periodo_sin_registros_termina_omitido(self):
        self.assertEqual(MotorPeriodos._determinar_estado_cierre(self.periodo), "omitido")

    def test_periodo_con_registro_incompleto_termina_caduco(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=None,
            payload_checklist={"vigencia": {"cumple": True}},
        )

        self.assertEqual(MotorPeriodos._determinar_estado_cierre(self.periodo), "caduco")

    def test_periodo_completo_y_operativo_termina_conforme(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=True,
            payload_checklist={
                "vigencia": {"cumple": True},
                "presion": {"cumple": True},
            },
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_b,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={"sello": {"cumple": True}},
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_sin_checklist,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={},
        )

        self.assertEqual(MotorPeriodos._determinar_estado_cierre(self.periodo), "operativo")

    def test_periodo_completo_con_observacion_termina_observado(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=True,
            payload_checklist={
                "vigencia": {"cumple": True},
                "presion": {"cumple": True},
            },
            observacion_general="Requiere seguimiento",
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_b,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={"sello": {"cumple": True}},
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_sin_checklist,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={},
        )

        self.assertEqual(MotorPeriodos._determinar_estado_cierre(self.periodo), "observado")

    def test_periodo_completo_con_falla_termina_fallido(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=False,
            payload_checklist={
                "vigencia": {"cumple": True},
                "presion": {"cumple": False},
            },
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_b,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={"sello": {"cumple": True}},
        )
        MotorFichas.crear_ficha(
            periodo=self.periodo,
            recurso=self.recurso_sin_checklist,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={},
        )

        self.assertEqual(MotorPeriodos._determinar_estado_cierre(self.periodo), "fallido")

    def test_estado_abierto_sin_fichas_completas_permanece_pendiente(self):
        self.assertEqual(
            MotorPeriodos._calcular_estado_abierto(self.nave, self.periodo),
            "pendiente",
        )

    def test_estado_abierto_con_una_ficha_completa_pasa_a_en_proceso(self):
        self._crear_ficha(
            recurso=self.recurso_a,
            estado_operativo=True,
            payload_checklist={
                "vigencia": {"cumple": True},
                "presion": {"cumple": True},
            },
        )

        self.assertEqual(
            MotorPeriodos._calcular_estado_abierto(self.nave, self.periodo),
            "en_proceso",
        )

    def test_ficha_con_requerimientos_exige_campo_cumple_en_cada_item(self):
        ficha = FichaRegistro.objects.create(
            periodo=self.periodo,
            recurso=self.recurso_a,
            usuario=self.usuario,
            estado_operativo=True,
            payload_checklist={"vigencia": True, "presion": True},
        )

        self.assertFalse(MotorPeriodos._es_ficha_completa(ficha))

    def test_ficha_sin_requerimientos_es_completa_si_tiene_estado_operativo(self):
        ficha = FichaRegistro.objects.create(
            periodo=self.periodo,
            recurso=self.recurso_sin_checklist,
            usuario=self.usuario,
            estado_operativo=False,
            payload_checklist={},
        )

        self.assertTrue(MotorPeriodos._es_ficha_completa(ficha))

    def test_sincronizar_periodos_nave_retorna_conteo_de_errores(self):
        periodicidad_extra = Periodicidad.objects.create(
            nombre="Diaria Estados",
            duracion_dias=1,
            offset_dias=0,
            responsabilidad="mar",
            visibilidad="todos",
        )

        original_crear_periodo_abierto = MotorPeriodos._crear_periodo_abierto

        def crear_periodo_con_fallo(nave, periodicidad, fecha_inicio):
            if periodicidad == periodicidad_extra:
                raise RuntimeError("fallo simulado de periodicidad")
            return original_crear_periodo_abierto(nave, periodicidad, fecha_inicio)

        with patch.object(
            MotorPeriodos,
            "_crear_periodo_abierto",
            side_effect=crear_periodo_con_fallo,
        ):
            with self.assertLogs("inventory.services", level="ERROR") as logs:
                stats = MotorPeriodos.sincronizar_periodos_nave(self.nave)

        self.assertEqual(stats["periodos_con_error"], 1)
        self.assertTrue(any("Error processing periodicidad" in linea for linea in logs.output))
        self.assertIn("periodos_creados", stats)
        self.assertIn("periodos_vencidos", stats)


class TestIntegracionMotorReglas(TestCase):
    REGLA_POR_ESLORA = {
        "atributo": "eslora",
        "condiciones": [
            {
                "operador": "<=",
                "valor": 10,
                "resultado_cantidad": 0,
                "resultado_visible": False,
            },
            {
                "operador": "<=",
                "valor": 30,
                "resultado_cantidad": 2,
                "resultado_visible": True,
            },
            {
                "operador": ">",
                "valor": 30,
                "resultado_cantidad": 4,
                "resultado_visible": True,
            },
        ],
        "fallback_cantidad": 0,
        "fallback_visible": False,
    }

    def setUp(self):
        self.naviera = Naviera.objects.create(
            nombre="Naviera Integración",
            rut="99999999-9",
            slug="naviera-integracion",
        )
        self.periodicidad = Periodicidad.objects.create(
            nombre="Semanal Integración",
            duracion_dias=7,
            offset_dias=1,
            responsabilidad="mar",
            visibilidad="todos",
        )
        self.proposito = Proposito.objects.create(
            nombre="Seguridad Integración",
            categoria="Seguridad",
            tipo="Material",
        )
        self.usuario = Usuario.objects.create_user(
            username="marinero_integracion",
            password="password-seguro-123",
            naviera=self.naviera,
            rut="99999999-9",
            email="marinero_integracion@example.com",
            rol="mar",
        )

    def _crear_nave(self, nombre, matricula, eslora, naviera=None):
        return Nave.objects.create(
            naviera=naviera or self.naviera,
            nombre=nombre,
            matricula=matricula,
            eslora=eslora,
            arqueo_bruto=200,
            capacidad_personas=12,
        )

    def _crear_recurso(
        self,
        nombre,
        regla_aplicacion,
        requerimientos=None,
        naviera=None,
        periodicidad=None,
        codigo=None,
        area=None,
    ):
        return Recurso.objects.create(
            naviera=naviera,
            proposito=self.proposito,
            periodicidad=periodicidad or self.periodicidad,
            area=area,
            nombre=nombre,
            codigo=codigo,
            requerimientos=requerimientos if requerimientos is not None else [],
            regla_aplicacion=regla_aplicacion,
        )

    def _get_matriz(self, nave, recurso):
        return MatrizNaveRecurso.objects.get(nave=nave, recurso=recurso)

    def _get_periodo(self, nave):
        return PeriodoRevision.objects.get(nave=nave, periodicidad=self.periodicidad)

    def _payload_con_cantidad(self, cantidad, **items):
        payload = dict(items)
        payload[MotorFichas.CANTIDAD_REQUISITO_KEY] = {
            "cumple": cantidad,
            "observacion": "",
        }
        return payload

    def test_nave_pequena_obtiene_cantidad_correcta_segun_eslora(self):
        """Nave con eslora=8 (<=10) debe tener cantidad=0 y es_visible=False"""
        recurso = self._crear_recurso(
            nombre="Extintor Integración Pequeña",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )
        nave = self._crear_nave("Lancha Integración", "INT-001", 8)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 0)
        self.assertFalse(matriz.es_visible)

    def test_nave_mediana_obtiene_cantidad_correcta_segun_eslora(self):
        """Nave con eslora=20 (<=30) debe tener cantidad=2 y es_visible=True"""
        recurso = self._crear_recurso(
            nombre="Extintor Integración Mediana",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )
        nave = self._crear_nave("Patrullera Integración", "INT-002", 20)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_nave_grande_obtiene_cantidad_correcta_segun_eslora(self):
        """Nave con eslora=50 (>30) debe tener cantidad=4 y es_visible=True"""
        recurso = self._crear_recurso(
            nombre="Extintor Integración Grande",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )
        nave = self._crear_nave("Buque Integración", "INT-003", 50)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 4)
        self.assertTrue(matriz.es_visible)

    def test_signal_post_save_nave_sincroniza_matriz_automaticamente(self):
        """Al crear una nave, el Signal dispara sincronización y MatrizNaveRecurso existe"""
        recurso = self._crear_recurso(
            nombre="Recurso Signal",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )

        nave = self._crear_nave("Nave Signal", "INT-004", 20)

        matriz = self._get_matriz(nave, recurso)
        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_editar_eslora_nave_actualiza_matriz(self):
        """Al editar la eslora de una nave, la matriz debe actualizarse con el nuevo valor"""
        recurso = self._crear_recurso(
            nombre="Recurso Actualizable",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )
        nave = self._crear_nave("Nave Editable", "INT-005", 20)

        matriz = self._get_matriz(nave, recurso)
        self.assertEqual(matriz.cantidad, 2)

        nave.eslora = 50
        nave.save()

        matriz.refresh_from_db()
        self.assertEqual(matriz.cantidad, 4)
        self.assertTrue(matriz.es_visible)

    def test_recurso_sin_regla_usa_fallback_default(self):
        """Recurso con regla_aplicacion=None usa fallback (0, True)"""
        recurso = self._crear_recurso(
            nombre="Recurso Sin Regla",
            regla_aplicacion=None,
        )
        nave = self._crear_nave("Nave Fallback", "INT-006", 20)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 0)
        self.assertTrue(matriz.es_visible)

    def test_recurso_global_aplica_a_todas_las_naves_del_tenant(self):
        """Un recurso global (naviera=None) debe aparecer en la matriz de todas las naves activas"""
        recurso = self._crear_recurso(
            nombre="Recurso Global Integración",
            regla_aplicacion=self.REGLA_POR_ESLORA,
        )
        nave_a = self._crear_nave("Nave Global A", "INT-007", 20)
        nave_b = self._crear_nave("Nave Global B", "INT-008", 50)

        self.assertTrue(MatrizNaveRecurso.objects.filter(nave=nave_a, recurso=recurso).exists())
        self.assertTrue(MatrizNaveRecurso.objects.filter(nave=nave_b, recurso=recurso).exists())

    def test_recurso_privado_no_aplica_a_naves_de_otro_tenant(self):
        """Un recurso privado de naviera_a no debe aparecer en matriz de naves de naviera_b"""
        naviera_b = Naviera.objects.create(
            nombre="Naviera Integración B",
            rut="88888888-8",
            slug="naviera-integracion-b",
        )
        recurso_privado = self._crear_recurso(
            nombre="Recurso Privado Tenant",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            naviera=self.naviera,
        )
        nave_a = self._crear_nave("Nave Privada A", "INT-009", 20)
        nave_b = self._crear_nave("Nave Privada B", "INT-010", 20, naviera=naviera_b)

        self.assertTrue(MatrizNaveRecurso.objects.filter(nave=nave_a, recurso=recurso_privado).exists())
        self.assertFalse(
            MatrizNaveRecurso.objects.filter(nave=nave_b, recurso=recurso_privado).exists()
        )

    def test_flujo_completo_ficha_operativa(self):
        """
        Flujo end-to-end:
        1. Crear nave con eslora=20 → Signal crea MatrizNaveRecurso (cantidad=2, visible=True)
        2. Crear recurso con requerimientos=["vigencia", "presion"]
        3. Verificar que PeriodoRevision existe en estado 'pendiente'
        4. Crear ficha con todos los requerimientos cumplidos y estado_operativo=True
        5. Verificar que período pasa a 'en_proceso'
        6. Verificar que _determinar_estado_cierre retorna 'operativo'
        """
        recurso = self._crear_recurso(
            nombre="Extintor Operativo",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Operativa", "INT-011", 20)

        matriz = self._get_matriz(nave, recurso)
        periodo = self._get_periodo(nave)

        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)
        self.assertEqual(periodo.estado, "pendiente")

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True,
                vigencia={"cumple": True, "observacion": ""},
                presion={"cumple": True, "observacion": ""},
            ),
        )

        periodo.refresh_from_db()

        self.assertTrue(ficha.estado_operativo)
        self.assertEqual(periodo.estado, "en_proceso")
        self.assertEqual(MotorPeriodos._determinar_estado_cierre(periodo), "operativo")

    def test_flujo_completo_ficha_con_fallo(self):
        """
        Flujo end-to-end con fallo:
        1. Crear nave → Signal crea MatrizNaveRecurso
        2. Crear ficha con requerimiento fallado (cumple=False, observacion='motivo')
           y estado_operativo=False
        3. Verificar que período está en 'en_proceso'
        4. Verificar que _determinar_estado_cierre retorna 'fallido'
        """
        recurso = self._crear_recurso(
            nombre="Extintor Con Falla",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Con Falla", "INT-012", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=False,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True,
                vigencia={"cumple": True, "observacion": ""},
                presion={"cumple": False, "observacion": "motivo"},
            ),
        )

        periodo.refresh_from_db()

        self.assertFalse(ficha.estado_operativo)
        self.assertEqual(periodo.estado, "en_proceso")
        self.assertEqual(MotorPeriodos._determinar_estado_cierre(periodo), "fallido")

    def test_flujo_completo_periodo_caduco(self):
        """
        Período que expira con ficha incompleta → caduco:
        1. Crear ficha parcial (estado_operativo=None, checklist incompleto)
        2. Verificar que _determinar_estado_cierre retorna 'caduco'
        """
        recurso = self._crear_recurso(
            nombre="Extintor Parcial",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Parcial", "INT-013", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True,
                vigencia={"cumple": True, "observacion": ""},
            ),
        )

        self.assertIsNone(ficha.estado_operativo)
        self.assertEqual(MotorPeriodos._determinar_estado_cierre(periodo), "caduco")

    def test_observacion_requerimiento_fallado_es_obligatoria(self):
        """
        Si un requerimiento tiene cumple=False y no tiene observación,
        MotorFichas.crear_ficha debe lanzar ValueError
        """
        recurso = self._crear_recurso(
            nombre="Extintor Sin Observación",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Sin Observación", "INT-014", 20)
        periodo = self._get_periodo(nave)

        with self.assertRaises(ValueError):
            MotorFichas.crear_ficha(
                periodo=periodo,
                recurso=recurso,
                usuario=self.usuario,
                estado_operativo=False,
                observacion_general="",
                payload_checklist=self._payload_con_cantidad(
                    True,
                    vigencia={"cumple": True, "observacion": ""},
                    presion={"cumple": False, "observacion": ""},
                ),
            )

    def test_estado_operativo_se_fuerza_false_si_hay_fallo_en_requerimiento(self):
        """
        Si hay requerimientos fallados, validar_estado_operativo retorna False
        cuando estado_operativo=True
        """
        recurso = self._crear_recurso(
            nombre="Extintor Validación",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )

        es_valido = MotorFichas.validar_estado_operativo(
            recurso=recurso,
            estado_operativo=True,
            payload_checklist=self._payload_con_cantidad(
                True,
                vigencia={"cumple": True, "observacion": ""},
                presion={"cumple": False, "observacion": "baja presión"},
            ),
            cantidad=2,
        )

        self.assertFalse(es_valido)

    def test_recurso_sin_requerimientos_y_sin_cantidad_sintetica_puede_guardarse_con_payload_vacio(self):
        """
        Un recurso con requerimientos=[] y cantidad<=1 permite payload_checklist={}
        y cualquier valor de estado_operativo.
        """
        recurso_ok = self._crear_recurso(
            nombre="Recurso Sin Checklist OK",
            regla_aplicacion=None,
            requerimientos=[],
        )
        recurso_falla = self._crear_recurso(
            nombre="Recurso Sin Checklist FALLA",
            regla_aplicacion=None,
            requerimientos=[],
        )
        nave = self._crear_nave("Nave Sin Checklist", "INT-015", 20)
        periodo = self._get_periodo(nave)

        ficha_ok = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso_ok,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist={},
        )
        ficha_falla = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso_falla,
            usuario=self.usuario,
            estado_operativo=False,
            observacion_general="",
            payload_checklist={},
        )

        self.assertEqual(ficha_ok.payload_checklist, {})
        self.assertTrue(ficha_ok.estado_operativo)
        self.assertEqual(ficha_falla.payload_checklist, {})
        self.assertFalse(ficha_falla.estado_operativo)

    def test_recurso_sin_requerimientos_y_cantidad_mayor_a_uno_exige_requisito_cantidad(self):
        recurso = self._crear_recurso(
            nombre="Recurso Solo Cantidad",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=[],
        )
        nave = self._crear_nave("Nave Solo Cantidad", "INT-018", 20)
        periodo = self._get_periodo(nave)

        with self.assertRaises(ValueError):
            MotorFichas.crear_ficha(
                periodo=periodo,
                recurso=recurso,
                usuario=self.usuario,
                estado_operativo=True,
                observacion_general="",
                payload_checklist={},
            )

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(True),
        )

        self.assertTrue(ficha.estado_operativo)

    def test_guardado_parcial_sin_cantidad_es_permitido(self):
        """
        Un guardado parcial (estado_operativo=None) no debe exigir __cantidad__
        aunque cantidad > 1. La validación completa solo ocurre al confirmar.
        """
        recurso = self._crear_recurso(
            nombre="Recurso Guardado Parcial",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Parcial Cantidad", "INT-021", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist={},
        )

        self.assertIsNone(ficha.estado_operativo)

    def test_calcular_estado_ficha_usa_cantidad(self):
        """
        calcular_estado_ficha debe retornar 'en_progreso' si falta __cantidad__
        cuando cantidad > 1, y 'completa' cuando está presente y cumplida.
        """
        recurso = self._crear_recurso(
            nombre="Recurso Estado Ficha",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )

        estado = MotorFichas.calcular_estado_ficha(
            recurso=recurso,
            estado_operativo=True,
            payload_checklist={"vigencia": {"cumple": True, "observacion": ""}},
            cantidad=2,
        )
        self.assertEqual(estado, "en_progreso")

        estado = MotorFichas.calcular_estado_ficha(
            recurso=recurso,
            estado_operativo=True,
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": True, "observacion": ""}
            ),
            cantidad=2,
        )
        self.assertEqual(estado, "completa")

    def test_calcular_estado_ficha_distingue_pendiente_y_en_progreso(self):
        recurso = self._crear_recurso(
            nombre="Recurso Estado Parcial",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "operatividad"],
        )

        estado = MotorFichas.calcular_estado_ficha(
            recurso=recurso,
            estado_operativo=None,
            payload_checklist={},
        )
        self.assertEqual(estado, "pendiente")

        estado = MotorFichas.calcular_estado_ficha(
            recurso=recurso,
            estado_operativo=None,
            payload_checklist={"vigencia": {"cumple": True, "observacion": ""}},
        )
        self.assertEqual(estado, "en_progreso")

    def test_crear_ficha_operativa_actualiza_ultimo_estado(self):
        """Crear ficha con estado_operativo=True setea ultimo_estado_operativo=True en matriz."""
        recurso = self._crear_recurso(
            nombre="Recurso Estado Persistente OK",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Estado OK", "INT-030", 20)
        periodo = self._get_periodo(nave)
        matriz = self._get_matriz(nave, recurso)
        self.assertIsNone(matriz.ultimo_estado_operativo)

        MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": True, "observacion": ""}
            ),
        )

        matriz.refresh_from_db()
        self.assertTrue(matriz.ultimo_estado_operativo)
        self.assertIsNotNone(matriz.ultimo_estado_operativo_en)

    def test_modificar_ficha_a_fallada_actualiza_ultimo_estado(self):
        """Modificar ficha a estado_operativo=False actualiza la matriz correctamente."""
        recurso = self._crear_recurso(
            nombre="Recurso Estado Persistente Fallo",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Estado Fallo", "INT-031", 20)
        periodo = self._get_periodo(nave)

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            observacion_general="",
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": True, "observacion": ""}
            ),
        )
        MotorFichas.modificar_ficha(
            ficha=ficha,
            usuario_modificador=self.usuario,
            estado_operativo=False,
            observacion_general="sin vigencia",
            payload_checklist=self._payload_con_cantidad(
                True, vigencia={"cumple": False, "observacion": "sin vigencia"}
            ),
        )

        matriz = self._get_matriz(nave, recurso)
        self.assertFalse(matriz.ultimo_estado_operativo)

    def test_guardado_parcial_no_altera_ultimo_estado(self):
        """Un guardado parcial (estado_operativo=None) no debe modificar ultimo_estado_operativo."""
        recurso = self._crear_recurso(
            nombre="Recurso Sin Alterar",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Sin Alterar", "INT-032", 20)
        periodo = self._get_periodo(nave)

        MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist={},
        )

        matriz = self._get_matriz(nave, recurso)
        self.assertIsNone(matriz.ultimo_estado_operativo)
        self.assertIsNone(matriz.ultimo_estado_operativo_en)

    def test_fallo_a_fallo_actualiza_timestamp(self):
        """fallo → fallo debe actualizar ultimo_estado_operativo_en aunque el valor no cambie."""
        import time

        recurso = self._crear_recurso(
            nombre="Recurso Fallo Timestamp",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Fallo Timestamp", "INT-033", 20)
        periodo = self._get_periodo(nave)
        payload_fallo = self._payload_con_cantidad(
            True, vigencia={"cumple": False, "observacion": "roto"}
        )

        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=False,
            observacion_general="roto",
            payload_checklist=payload_fallo,
        )
        matriz = self._get_matriz(nave, recurso)
        ts_1 = matriz.ultimo_estado_operativo_en

        time.sleep(0.01)

        MotorFichas.modificar_ficha(
            ficha=ficha,
            usuario_modificador=self.usuario,
            estado_operativo=False,
            observacion_general="sigue roto",
            payload_checklist=payload_fallo,
        )
        matriz.refresh_from_db()
        self.assertFalse(matriz.ultimo_estado_operativo)
        self.assertGreater(matriz.ultimo_estado_operativo_en, ts_1)

    def test_recurso_nuevo_no_aparece_en_historial_anterior(self):
        """
        Un recurso creado después del cierre de un período
        no debe aparecer en el historial de ese período.
        """
        from datetime import timedelta
        from inventory.views import _construir_recursos_lista_periodo

        nave = self._crear_nave("Nave Historial Fantasma", "INT-040", 15)
        periodo = self._get_periodo(nave)

        periodo.fecha_termino = timezone.now().date() - timedelta(days=5)
        periodo.estado = "operativo"
        periodo.save()

        self._crear_recurso(
            nombre="Recurso Fantasma",
            regla_aplicacion=None,
            requerimientos=[],
        )
        MotorReglasSITREP.sincronizar_matriz_nave(nave)

        recursos = _construir_recursos_lista_periodo(nave, periodo, for_history=True)
        nombres = [r["recurso"].nombre for r in recursos]
        self.assertNotIn("Recurso Fantasma", nombres)

    def test_recursos_se_ordenan_por_segundo_tramo_del_codigo_dentro_del_area(self):
        from inventory.views import _construir_recursos_lista_periodo

        area_salvamento = Area.objects.create(nombre="Salvamento")
        area_incendio = Area.objects.create(nombre="Incendio")
        nave = self._crear_nave("Nave Orden Codigos", "INT-041", 15)
        periodo = self._get_periodo(nave)

        self._crear_recurso(
            nombre="Salvamento 15",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.15-Q",
        )
        self._crear_recurso(
            nombre="Salvamento 1",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.1-Q",
        )
        self._crear_recurso(
            nombre="Salvamento 21",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.21-Q",
        )
        self._crear_recurso(
            nombre="Salvamento 8",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.8-Q",
        )
        self._crear_recurso(
            nombre="Incendio 10",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_incendio,
            codigo="2.10-Q",
        )
        self._crear_recurso(
            nombre="Incendio 3",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_incendio,
            codigo="2.3-Q",
        )
        MotorReglasSITREP.sincronizar_matriz_nave(nave)

        recursos = _construir_recursos_lista_periodo(nave, periodo)

        codigos_salvamento = [
            item["recurso"].codigo for item in recursos if item["recurso"].area_id == area_salvamento.id
        ]
        codigos_incendio = [
            item["recurso"].codigo for item in recursos if item["recurso"].area_id == area_incendio.id
        ]

        self.assertEqual(codigos_salvamento, ["1.1-Q", "1.8-Q", "1.15-Q", "1.21-Q"])
        self.assertEqual(codigos_incendio, ["2.3-Q", "2.10-Q"])

    def test_grupos_de_areas_se_ordenan_por_orden_y_no_por_nombre(self):
        from inventory.views import _agrupar_recursos_por_area, _construir_recursos_lista_periodo

        area_zeta = Area.objects.create(nombre="Zeta", orden=1)
        area_alfa = Area.objects.create(nombre="Alfa", orden=2)
        nave = self._crear_nave("Nave Orden Areas", "INT-042", 15)
        periodo = self._get_periodo(nave)

        self._crear_recurso(
            nombre="Recurso Zeta",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_zeta,
            codigo="9.1-Q",
        )
        self._crear_recurso(
            nombre="Recurso Alfa",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_alfa,
            codigo="1.1-Q",
        )
        MotorReglasSITREP.sincronizar_matriz_nave(nave)

        recursos = _construir_recursos_lista_periodo(nave, periodo)
        grupos = _agrupar_recursos_por_area(recursos)

        self.assertEqual([grupo["area"].id for grupo in grupos], [area_zeta.id, area_alfa.id])

    def test_registros_se_ordenan_por_codigo_dentro_del_area(self):
        from inventory.views import _agrupar_registros_por_area

        area_salvamento = Area.objects.create(nombre="Salvamento")
        recurso_15 = self._crear_recurso(
            nombre="Salvamento 15",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.15-Q",
        )
        recurso_1 = self._crear_recurso(
            nombre="Salvamento 1",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.1-Q",
        )
        recurso_21 = self._crear_recurso(
            nombre="Salvamento 21",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.21-Q",
        )
        recurso_8 = self._crear_recurso(
            nombre="Salvamento 8",
            regla_aplicacion=None,
            requerimientos=[],
            area=area_salvamento,
            codigo="1.8-Q",
        )

        grupos = _agrupar_registros_por_area(
            [
                {"tipo": "pendiente", "recurso": recurso_15},
                {"tipo": "pendiente", "recurso": recurso_1},
                {"tipo": "pendiente", "recurso": recurso_21},
                {"tipo": "pendiente", "recurso": recurso_8},
            ]
        )

        self.assertEqual(
            [registro["recurso"].codigo for registro in grupos[0]["registros"]],
            ["1.1-Q", "1.8-Q", "1.15-Q", "1.21-Q"],
        )

    def test_numero_periodo_se_calcula_con_reset_anual_desde_agregado_en(self):
        from inventory.views import _numero_periodo

        nave = self._crear_nave("Nave Periodos", "INT-043", 15)
        nave.agregado_en = timezone.make_aware(datetime(2026, 1, 1, 9, 0, 0))

        periodo_1 = PeriodoRevision(
            nave=nave,
            periodicidad=self.periodicidad,
            fecha_inicio=date(2026, 1, 1),
            fecha_termino=date(2026, 1, 7),
        )
        periodo_12 = PeriodoRevision(
            nave=nave,
            periodicidad=self.periodicidad,
            fecha_inicio=date(2026, 3, 19),
            fecha_termino=date(2026, 3, 25),
        )
        periodo_reset = PeriodoRevision(
            nave=nave,
            periodicidad=self.periodicidad,
            fecha_inicio=date(2026, 12, 31),
            fecha_termino=date(2027, 1, 6),
        )
        periodo_anterior = PeriodoRevision(
            nave=nave,
            periodicidad=self.periodicidad,
            fecha_inicio=date(2025, 12, 25),
            fecha_termino=date(2025, 12, 31),
        )

        self.assertEqual(_numero_periodo(periodo_1, nave), 1)
        self.assertEqual(_numero_periodo(periodo_12, nave), 12)
        self.assertEqual(_numero_periodo(periodo_reset, nave), 1)
        self.assertIsNone(_numero_periodo(periodo_anterior, nave))

    def test_construir_recursos_lista_periodo_expone_estado_ficha_pendiente(self):
        from inventory.views import _construir_recursos_lista_periodo

        recurso = self._crear_recurso(
            nombre="Recurso Pendiente Persistido",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia"],
        )
        nave = self._crear_nave("Nave Estado Ficha", "INT-044", 20)
        periodo = self._get_periodo(nave)
        ficha = MotorFichas.crear_ficha(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=None,
            observacion_general="",
            payload_checklist={},
        )
        ficha.estado_ficha = "pendiente"
        ficha.save(update_fields=["estado_ficha"])

        recursos = _construir_recursos_lista_periodo(nave, periodo)
        item = next(item for item in recursos if item["recurso"].id == recurso.id)

        self.assertTrue(item["tiene_ficha"])
        self.assertEqual(item["estado_ficha"], "pendiente")
        self.assertIsNone(item["estado_operativo"])

    def test_requisito_cantidad_fallado_exige_observacion(self):
        recurso = self._crear_recurso(
            nombre="Recurso Cantidad Fallida",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=[],
        )
        nave = self._crear_nave("Nave Cantidad Fallida", "INT-019", 20)
        periodo = self._get_periodo(nave)

        with self.assertRaises(ValueError):
            MotorFichas.crear_ficha(
                periodo=periodo,
                recurso=recurso,
                usuario=self.usuario,
                estado_operativo=False,
                observacion_general="",
                payload_checklist={
                    MotorFichas.CANTIDAD_REQUISITO_KEY: {
                        "cumple": False,
                        "observacion": "",
                    }
                },
            )

    def test_construir_checklist_items_agrega_cantidad_al_final(self):
        recurso = self._crear_recurso(
            nombre="Recurso Checklist Cantidad",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )

        checklist = MotorFichas.construir_checklist_items(
            recurso=recurso,
            cantidad=4,
            payload_checklist={},
        )

        self.assertEqual(
            [item["key"] for item in checklist],
            ["vigencia", "presion", MotorFichas.CANTIDAD_REQUISITO_KEY],
        )
        self.assertEqual(checklist[-1]["label"], "Cantidad: 4")

    def test_ficha_legacy_sin_requisito_cantidad_sigue_completa(self):
        recurso = self._crear_recurso(
            nombre="Recurso Legacy Cantidad",
            regla_aplicacion=self.REGLA_POR_ESLORA,
            requerimientos=["vigencia", "presion"],
        )
        nave = self._crear_nave("Nave Legacy Cantidad", "INT-020", 20)
        periodo = self._get_periodo(nave)

        ficha = FichaRegistro.objects.create(
            periodo=periodo,
            recurso=recurso,
            usuario=self.usuario,
            estado_operativo=True,
            payload_checklist={
                "vigencia": {"cumple": True, "observacion": ""},
                "presion": {"cumple": True, "observacion": ""},
            },
        )

        self.assertTrue(MotorPeriodos._es_ficha_completa(ficha))

    def test_regla_con_atributo_inexistente_usa_fallback(self):
        """regla_aplicacion con atributo='campo_inexistente' retorna fallback"""
        recurso = self._crear_recurso(
            nombre="Recurso Atributo Inválido",
            regla_aplicacion={
                "atributo": "campo_inexistente",
                "condiciones": [
                    {
                        "operador": "<=",
                        "valor": 10,
                        "resultado_cantidad": 99,
                        "resultado_visible": True,
                    }
                ],
                "fallback_cantidad": 7,
                "fallback_visible": False,
            },
        )
        nave = self._crear_nave("Nave Fallback Regla", "INT-016", 20)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 7)
        self.assertFalse(matriz.es_visible)

    def test_regla_con_operador_invalido_ignora_condicion(self):
        """Una condición con operador no reconocido se ignora y continúa evaluando"""
        recurso = self._crear_recurso(
            nombre="Recurso Operador Inválido",
            regla_aplicacion={
                "atributo": "eslora",
                "condiciones": [
                    {
                        "operador": "!==",
                        "valor": 20,
                        "resultado_cantidad": 99,
                        "resultado_visible": False,
                    },
                    {
                        "operador": "<=",
                        "valor": 30,
                        "resultado_cantidad": 2,
                        "resultado_visible": True,
                    },
                ],
                "fallback_cantidad": 0,
                "fallback_visible": False,
            },
        )
        nave = self._crear_nave("Nave Operador Inválido", "INT-017", 20)

        matriz = self._get_matriz(nave, recurso)

        self.assertEqual(matriz.cantidad, 2)
        self.assertTrue(matriz.es_visible)

    def test_payload_checklist_legacy_booleano_se_normaliza(self):
        """
        Un payload legacy {"req": True} debe normalizarse a {"req": {"cumple": True, "observacion": ""}}
        mediante MotorFichas.normalizar_payload_checklist()
        """
        payload_normalizado = MotorFichas.normalizar_payload_checklist({"req": True})

        self.assertEqual(
            payload_normalizado,
            {"req": {"cumple": True, "observacion": ""}},
        )

    def test_payload_checklist_sin_campo_observacion_se_completa(self):
        """
        Un payload {"req": {"cumple": True}} sin "observacion" debe normalizarse
        agregando "observacion": ""
        """
        payload_normalizado = MotorFichas.normalizar_payload_checklist(
            {"req": {"cumple": True}}
        )

        self.assertEqual(
            payload_normalizado,
            {"req": {"cumple": True, "observacion": ""}},
        )
