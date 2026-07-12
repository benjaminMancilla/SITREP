"""
catalog/management/commands/importar_catalogo_completo.py

Reemplaza la versión central COMPLETA del catálogo dinámico a partir de un
JSON externo — pensado para una carga masiva única (ej. el cliente entrega
una revisión completa de su catálogo antes de entrar a producción real).
Distinto de `load_recursos` (inspection): ese es idempotente/aditivo, este
tombstonea todo lo activo en central y publica el JSON entero como raíces
nuevas, en un solo commit de catálogo (una CatalogoVersion). Ver el
docstring de `importar_version_completa_central` en catalog/services.py
para el detalle de por qué el reemplazo es "ciego" y cuándo hay que
endurecerlo (una vez el catálogo esté en producción real).

Uso:
    python manage.py importar_catalogo_completo catalogo.json

    # Dry-run (no escribe nada, solo reporta qué haría):
    python manage.py importar_catalogo_completo catalogo.json --dry-run

Formato del JSON esperado — lista de grupos área+periodicidad+propósito,
cada uno con sus recursos:

    [
      {
        "area": "Salvamento",
        "periodicidad": "Semanal",
        "proposito": "MATERIAL DE SEGURIDAD",
        "recursos": [
          {
            "nombre": "Chaleco Salvavidas",
            "codigo": "3.3-Q",
            "descripcion": "Chaleco tipo I",
            "requerimientos": ["Vigencia", "Talla correcta"],
            "regla_aplicacion": null
          }
        ]
      }
    ]

- "periodicidad" debe existir ya (créala en /admin/ antes de importar).
- "proposito" se infiere de "SEGURIDAD"/"OPERACIONAL" en el texto; "area"
  se crea sola si no existe.
- "requerimientos" acepta lista de strings simples (formato legado, se
  convierten a requerimientos tipados "estandar") o ya en formato tipado
  ([{"id": ..., "tipo": "estandar"|"condicion"|"cantidad", "texto": ...}])
  si necesitas requerimientos de condición/cantidad.
- "regla_aplicacion" es opcional — mismo schema que CatalogRuleEngine
  (ver catalog/services.py).
- "codigo" y "descripcion" son opcionales.

Todo el JSON se valida antes de escribir nada: si cualquier grupo o recurso
falla al parsear, no se toca la base de datos.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sitrep.catalog.services import importar_version_completa_central


class Command(BaseCommand):
    help = "Reemplaza la versión central completa del catálogo dinámico desde un JSON"

    def add_arguments(self, parser):
        parser.add_argument("json_file", type=str, help="Ruta al JSON del catálogo completo")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Muestra qué se crearía/desactivaría sin escribir en la BD",
        )

    def handle(self, *args, **options):
        json_path = Path(options["json_file"])
        if not json_path.exists():
            raise CommandError(f"Archivo no encontrado: {json_path}")

        dry_run = options["dry_run"]
        json_data = json.loads(json_path.read_text(encoding="utf-8"))

        resumen = importar_version_completa_central(json_data, dry_run=dry_run)

        if resumen["errores"]:
            self.stderr.write(self.style.ERROR(f"{len(resumen['errores'])} error(es) — no se escribió nada:"))
            for error in resumen["errores"]:
                self.stderr.write(self.style.ERROR(f"  ✗ {error}"))
            raise CommandError("Corrige el JSON e intenta de nuevo.")

        self.stdout.write(self.style.SUCCESS(
            f"  Grupos procesados:        {resumen['grupos']}\n"
            f"  Recursos nuevos:          {resumen['recursos_nuevos']}\n"
            f"  Recursos desactivados:    {resumen['recursos_desactivados']}"
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("  [DRY RUN — nada fue escrito en la BD]"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  Nueva CatalogoVersion central: v{resumen['version_numero']}"))
