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

from .pdf_plotly_fallback import plotly_bar_fallback


LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "valenet_logo.png"


def _table(df: pd.DataFrame, font_size: int = 7) -> Table:
    if df.empty and len(df.columns) == 0:
        df = pd.DataFrame([{"Aviso": "Sem dados disponiveis para esta secao."}])
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
            ]
        )
    )
    return table


def _summary_table(df: pd.DataFrame) -> Table:
    if df.empty:
        return _table(pd.DataFrame([{"Aviso": "Sem dados disponiveis para esta secao."}]), font_size=8)
    row = df.iloc[0].to_dict()
    data = [["Indicador", "Valor"]] + [[str(key), str(value)] for key, value in row.items()]
    table = Table(data, repeatRows=1, colWidths=[8.5 * cm, 7.5 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9E2F3")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FB")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _figure_image(figure: Figure, title: str = "") -> Image | Paragraph:
    return plotly_bar_fallback(figure, title)


def _footer(canvas, _doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(1.2 * cm, 0.8 * cm, f"Gerado em {datetime.now():%d/%m/%Y %H:%M}")
    if LOGO_PATH.exists():
        canvas.drawImage(str(LOGO_PATH), 25.2 * cm, 0.45 * cm, width=3.3 * cm, height=1.0 * cm, preserveAspectRatio=True, mask="auto")
    canvas.restoreState()


def generate_charge_ai_pdf(
    output_path: str | Path,
    period: str,
    summary_df: pd.DataFrame,
    ia_df: pd.DataFrame,
    charge_df: pd.DataFrame,
    status_df: pd.DataFrame,
    type_df: pd.DataFrame,
    recurrence_df: pd.DataFrame,
    classification_df: pd.DataFrame,
    daily_df: pd.DataFrame,
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
        title="Analise de Cobranca com IA",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TitleCenter", parent=styles["Title"], alignment=TA_CENTER, fontSize=22, leading=28, textColor=colors.HexColor("#12355B"))
    subtitle = ParagraphStyle("SubtitleCenter", parent=styles["Heading2"], alignment=TA_CENTER, fontSize=13, textColor=colors.HexColor("#344054"))

    story = [
        Spacer(1, 2.2 * cm),
        Paragraph("Analise de Cobranca com IA", title),
        Spacer(1, 0.25 * cm),
        Paragraph(f"Periodo analisado: {period}", subtitle),
        PageBreak(),
        Paragraph("Resumo geral", styles["Heading2"]),
        _summary_table(summary_df),
        Spacer(1, 0.5 * cm),
        Paragraph("Conclusao automatica", styles["Heading2"]),
        Paragraph(conclusion, styles["BodyText"]),
        PageBreak(),
        Paragraph("Analise da IA Velma", styles["Heading2"]),
        _table(ia_df, font_size=7),
        Spacer(1, 0.5 * cm),
        Paragraph("Analise de cobranca", styles["Heading2"]),
        _table(charge_df, font_size=7),
        PageBreak(),
        Paragraph("Status", styles["Heading2"]),
        _table(status_df, font_size=7),
        Spacer(1, 0.5 * cm),
        Paragraph("Tipo de atendimento", styles["Heading2"]),
        _table(type_df, font_size=7),
        Spacer(1, 0.5 * cm),
        Paragraph("Recorrencia", styles["Heading2"]),
        _table(recurrence_df, font_size=7),
        PageBreak(),
        Paragraph("Classificacao", styles["Heading2"]),
        _table(classification_df, font_size=6),
        Spacer(1, 0.5 * cm),
        Paragraph("Analise por dia", styles["Heading2"]),
        _table(daily_df, font_size=6),
        PageBreak(),
    ]

    for index, (title_text, figure) in enumerate(figures, start=1):
        story.append(Paragraph(title_text, styles["Heading2"]))
        story.append(_figure_image(figure, title_text))
        if index % 2 == 0 and index != len(figures):
            story.append(PageBreak())
        else:
            story.append(Spacer(1, 0.4 * cm))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf_bytes = buffer.getvalue()
    output_path.write_bytes(pdf_bytes)
    return pdf_bytes
