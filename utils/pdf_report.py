from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
from plotly.graph_objects import Figure
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _dataframe_table(df: pd.DataFrame, font_size: int = 7) -> Table:
    data = [list(df.columns)] + df.astype(str).values.tolist()
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9E2F3")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FB")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _footer(canvas, _doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    canvas.drawString(1.2 * cm, 0.8 * cm, f"Gerado em {generated}")
    canvas.drawRightString(28.5 * cm, 0.8 * cm, f"Pagina {canvas.getPageNumber()}")
    canvas.restoreState()


def _figure_image(figure: Figure) -> Image | Paragraph:
    try:
        image_bytes = figure.to_image(format="png", width=1200, height=620, scale=2)
        image = Image(BytesIO(image_bytes), width=25 * cm, height=12.9 * cm)
        return image
    except Exception as exc:  # noqa: BLE001 - PDF should still be generated without image export.
        styles = getSampleStyleSheet()
        return Paragraph(f"Nao foi possivel renderizar este grafico no PDF: {exc}", styles["BodyText"])


def generate_pdf(
    output_path: str | Path,
    months: tuple[str, str],
    summary_df: pd.DataFrame,
    group_df: pd.DataFrame,
    figures: list[tuple[str, Figure]],
    conclusion: str,
) -> bytes:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.1 * cm,
        leftMargin=1.1 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.3 * cm,
        title="Analise Comparativa de TMA, TME e Inatividade",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleCenter",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=22,
        leading=28,
        textColor=colors.HexColor("#12355B"),
    )
    subtitle = ParagraphStyle(
        "SubtitleCenter",
        parent=styles["Heading2"],
        alignment=TA_CENTER,
        fontSize=13,
        textColor=colors.HexColor("#344054"),
    )

    story = [
        Spacer(1, 2.5 * cm),
        Paragraph("Analise Comparativa de TMA, TME e Inatividade", title),
        Spacer(1, 0.25 * cm),
        Paragraph("Mudanca de Endereco + Mudanca de Comodo", subtitle),
        Spacer(1, 0.2 * cm),
        Paragraph(f"Periodo: {months[0]} x {months[1]}", subtitle),
        PageBreak(),
        Paragraph("Resumo geral dos meses", styles["Heading2"]),
        _dataframe_table(summary_df, font_size=8),
        Spacer(1, 0.5 * cm),
        Paragraph("Recorte com taxa / sem taxa / sem identificacao", styles["Heading2"]),
        _dataframe_table(group_df, font_size=6),
        PageBreak(),
    ]

    for index, (title_text, figure) in enumerate(figures, start=1):
        story.append(Paragraph(title_text, styles["Heading2"]))
        story.append(_figure_image(figure))
        if index % 2 == 0 and index != len(figures):
            story.append(PageBreak())
        else:
            story.append(Spacer(1, 0.4 * cm))

    story.extend(
        [
            PageBreak(),
            Paragraph("Conclusao automatica", styles["Heading2"]),
            Paragraph(conclusion, styles["BodyText"]),
        ]
    )

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf_bytes = buffer.getvalue()
    output_path.write_bytes(pdf_bytes)
    return pdf_bytes

