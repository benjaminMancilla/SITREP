"""
inventory/management/commands/load_recursos.py

Carga recursos y requerimientos desde el JSON generado por extract_recursos.py.

Uso:
    # Recursos globales (todas las navieras):
    python manage.py load_recursos recursos.json --global

    # Recursos privados de una naviera:
    python manage.py load_recursos recursos.json --naviera <slug>

    # Dry-run:
    python manage.py load_recursos recursos.json --global --dry-run

Comportamiento:
- Idempotente: si el recurso ya existe (mismo nombre + periodicidad + área), lo omite.
- Crea Area y Proposito si no existen (ambos son globales en el modelo).
- Busca Periodicidad por nombre (global, no tenant-scoped).
- NO crea naves ni fichas — solo la estructura de recursos.
- Filosofía de robustez: errores por ítem no detienen el batch.
"""

import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)

# Lógica de carga reutilizable desde la vista del admin
def ejecutar_carga(json_data: list, naviera=None, dry_run: bool = False) -> dict:
    """
    Núcleo de carga. Acepta los datos ya parseados como lista de dicts.
    Retorna estadísticas: {areas_creadas, recursos_creados, recursos_omitidos, errores, log}.
    naviera=None → recursos globales.
    """
    from inventory.models import Area, Naviera, Periodicidad, Proposito, Recurso

    stats = {
        "areas_creadas": 0,
        "propositos_creados": 0,
        "recursos_creados": 0,
        "recursos_omitidos": 0,
        "errores": 0,
        "log": [],  # lista de (nivel, mensaje) para mostrar en el admin
    }

    def log(nivel, msg):
        stats["log"].append((nivel, msg))
        logger.debug(msg) if nivel == "info" else logger.error(msg)

    for entrada in json_data:
        try:
            _procesar_entrada(entrada, naviera, dry_run, stats, log)
        except Exception as e:
            stats["errores"] += 1
            logger.error(
                "Error procesando entrada nave=%r area=%r: %s",
                entrada.get("nave"), entrada.get("area"), e,
                exc_info=True,
            )
            log("error", f"✗ nave={entrada.get('nave')!r} area={entrada.get('area')!r}: {e}")

    return stats


def _procesar_entrada(entrada, naviera, dry_run, stats, log):
    from inventory.models import Area, Periodicidad, Proposito, Recurso

    nombre_area = entrada["area"]
    nombre_periodicidad = entrada["periodicidad"]
    proposito_str = entrada["proposito"]
    recursos = entrada["recursos"]

    # ── Periodicidad (global) ─────────────────────────────────────────────
    try:
        periodicidad = Periodicidad.objects.get(nombre__iexact=nombre_periodicidad)
    except Periodicidad.DoesNotExist:
        raise ValueError(
            f"Periodicidad {nombre_periodicidad!r} no existe. "
            "Créala en el admin antes de importar."
        )

    # ── Proposito (global) ────────────────────────────────────────────────
    # "MATERIAL DE SEGURIDAD" → tipo=Material, categoria=Seguridad
    # "MATERIAL OPERACIONAL"  → tipo=Material, categoria=Operacional
    proposito_upper = proposito_str.upper()
    if "SEGURIDAD" in proposito_upper:
        cat = "Seguridad"
    elif "OPERACIONAL" in proposito_upper:
        cat = "Operacional"
    else:
        raise ValueError(
            f"No se pudo inferir categoría de propósito desde {proposito_str!r}. "
            "Esperado 'SEGURIDAD' u 'OPERACIONAL' en el texto."
        )

    if not dry_run:
        proposito_obj, prop_creado = Proposito.objects.get_or_create(
            categoria=cat,
            tipo="Material",
            defaults={"nombre": proposito_str.title()},
        )
    else:
        prop_creado = not Proposito.objects.filter(categoria=cat, tipo="Material").exists()
        proposito_obj = None

    if prop_creado:
        stats["propositos_creados"] += 1
        log("info", f"  + Propósito creado: Material / {cat}")

    # ── Area (global — unique por nombre) ─────────────────────────────────
    if not dry_run:
        with transaction.atomic():
            area, area_creada = Area.objects.get_or_create(
                nombre=nombre_area,
                defaults={"nombre_tecnico": nombre_area},
            )
    else:
        area_creada = not Area.objects.filter(nombre=nombre_area).exists()
        area = None

    if area_creada:
        stats["areas_creadas"] += 1
        log("info", f"  + Área creada: {nombre_area!r}")

    # ── Recursos ──────────────────────────────────────────────────────────
    for recurso_data in recursos:
        try:
            _procesar_recurso(
                recurso_data=recurso_data,
                area=area,
                nombre_area=nombre_area,
                periodicidad=periodicidad,
                proposito_obj=proposito_obj,
                naviera=naviera,
                dry_run=dry_run,
                stats=stats,
                log=log,
            )
        except Exception as e:
            stats["errores"] += 1
            logger.error(
                "Error procesando recurso %r: %s",
                recurso_data.get("nombre"), e,
                exc_info=True,
            )
            log("error", f"    ✗ recurso={recurso_data.get('nombre')!r}: {e}")


def _procesar_recurso(
    recurso_data, area, nombre_area, periodicidad,
    proposito_obj, naviera, dry_run, stats, log,
):
    from inventory.models import Recurso

    nombre = recurso_data["nombre"]
    requerimientos = recurso_data["requerimientos"]

    # Idempotencia: mismo nombre + periodicidad + área
    existe = Recurso.objects.filter(
        nombre=nombre,
        periodicidad=periodicidad,
        area__nombre=nombre_area,
    ).exists()

    if existe:
        stats["recursos_omitidos"] += 1
        log("info", f"    ~ Omitido (ya existe): {nombre!r}")
        return

    if dry_run:
        stats["recursos_creados"] += 1
        log("info", f"    [DRY] crearía: {nombre!r} ({len(requerimientos)} reqs)")
        return

    with transaction.atomic():
        Recurso.objects.create(
            nombre=nombre,
            codigo=recurso_data.get("codigo"),
            descripcion=recurso_data.get("descripcion"),
            periodicidad=periodicidad,
            area=area,
            proposito=proposito_obj,
            naviera=naviera,           # None = global, obj = privado
            requerimientos=requerimientos,
            regla_aplicacion=None,
        )

    stats["recursos_creados"] += 1
    log("info", f"    + Recurso: {nombre!r} ({len(requerimientos)} reqs)")


# ── Management command ────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Carga recursos y requerimientos desde JSON de inspección"

    def add_arguments(self, parser):
        parser.add_argument("json_file", type=str, help="Ruta al JSON de recursos")
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument(
            "--global", dest="global_scope", action="store_true",
            help="Crear recursos globales (naviera=None, visibles para todos)",
        )
        scope.add_argument(
            "--naviera", type=str, dest="naviera_slug",
            help="Slug de la naviera para recursos privados",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Muestra qué se crearía sin escribir en la BD",
        )

    def handle(self, *args, **options):
        from inventory.models import Naviera

        json_path = Path(options["json_file"])
        if not json_path.exists():
            raise CommandError(f"Archivo no encontrado: {json_path}")

        naviera = None
        if options["naviera_slug"]:
            try:
                naviera = Naviera.objects.get(slug=options["naviera_slug"])
            except Naviera.DoesNotExist:
                raise CommandError(f"Naviera {options['naviera_slug']!r} no existe")

        dry_run = options["dry_run"]
        json_data = json.loads(json_path.read_text(encoding="utf-8"))

        stats = ejecutar_carga(json_data, naviera=naviera, dry_run=dry_run)

        for nivel, msg in stats["log"]:
            if nivel == "error":
                self.stderr.write(self.style.ERROR(msg))
            else:
                self.stdout.write(msg)

        self.stdout.write("\n" + "─" * 50)
        self.stdout.write(self.style.SUCCESS(
            f"  Áreas creadas:      {stats['areas_creadas']}\n"
            f"  Propósitos creados: {stats['propositos_creados']}\n"
            f"  Recursos creados:   {stats['recursos_creados']}\n"
            f"  Recursos omitidos:  {stats['recursos_omitidos']}\n"
            f"  Errores:            {stats['errores']}"
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("  [DRY RUN — nada fue escrito en la BD]"))