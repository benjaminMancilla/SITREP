import io

from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML

from sitrep.accounts.audit import registrar_acceso

from .. import presenters


def generar_pdf_periodo(request, nave, periodo, slug):
    """
    Renderiza el PDF de ficha de un período. Compartido entre el flujo kiosco
    (sesión de nave en mar) y el flujo tierra (naves/<id>/periodos/<id>/pdf/).
    """
    recursos_lista = presenters.construir_recursos_lista_periodo(nave, periodo, slug=slug)
    areas_grupos = presenters.agrupar_recursos_por_area(recursos_lista)

    areas_param = request.GET.get("areas", "").strip()
    if areas_param:
        areas_seleccionadas = set(areas_param.split(","))
        areas_grupos = [
            grupo for grupo in areas_grupos
            if (str(grupo["area"].id) if grupo["area"] else "none") in areas_seleccionadas
        ]

    modo_bn = request.GET.get("modo") == "bn"

    presenters.adjuntar_colores_pdf(areas_grupos)

    html_string = render_to_string(
        "inspection/kiosco/ficha_pdf.html",
        {
            "nave": nave,
            "periodo": periodo,
            "areas_grupos": areas_grupos,
            "naviera": request.naviera,
            "modo_bn": modo_bn,
        },
        request=request,
    )

    pdf_file = io.BytesIO()
    HTML(string=html_string, base_url=request.build_absolute_uri("/")).write_pdf(pdf_file)
    pdf_file.seek(0)

    nombre_archivo = f"ficha_{nave.matricula}_{periodo.periodicidad.nombre}_{periodo.fecha_inicio}.pdf"
    registrar_acceso(
        request, "export", "ficha_pdf",
        detalle=f"nave={nave.matricula} periodo_id={periodo.id}",
    )
    response = HttpResponse(pdf_file.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{nombre_archivo}"'
    return response
