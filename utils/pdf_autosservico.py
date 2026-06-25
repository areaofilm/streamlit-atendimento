from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "valenet_logo.png"


def _table(df: pd.DataFrame, font_size: int = 7, max_rows: int | None = None, col_widths: list[float] | None = None) -> Table:
    if df.empty and len(df.columns) == 0:
        df = pd.DataFrame([{"Aviso": "Sem dados disponiveis para esta secao."}])
    shown = df.head(max_rows) if max_rows else df
    data = [list(shown.columns)] + shown.astype(str).values.tolist()
    table = Table(data, repeatRows=1, colWidths=col_widths)
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
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _compact_metric_table(df: pd.DataFrame, label_col: str) -> pd.DataFrame:
    columns = [
        label_col,
        "Atendimentos",
        "% volume",
        "OS_executadas",
        "% OS executadas",
        "Faturas_pagas",
        "Valor_faturas_pagas",
        "% Faturas pagas",
        "Avaliacoes_CSAT",
        "% CSAT positivo",
    ]
    available = [column for column in columns if column in df.columns]
    compact = df[available].copy() if available else df.copy()
    return compact.rename(
        columns={
            label_col: label_col,
            "Atendimentos": "Atend.",
            "% volume": "% Vol.",
            "OS_executadas": "OS exec.",
            "% OS executadas": "% OS exec.",
            "Faturas_pagas": "Fat. pagas",
            "Valor_faturas_pagas": "Valor pago",
            "% Faturas pagas": "% Fat. pagas",
            "Avaliacoes_CSAT": "Aval. CSAT",
            "% CSAT positivo": "% CSAT +",
        }
    )


def _footer(canvas, _doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(1.2 * cm, 0.8 * cm, f"Gerado em {datetime.now():%d/%m/%Y %H:%M}")
    if LOGO_PATH.exists():
        canvas.drawImage(
            str(LOGO_PATH),
            25.2 * cm,
            0.45 * cm,
            width=3.3 * cm,
            height=1.0 * cm,
            preserveAspectRatio=True,
            mask="auto",
        )
    canvas.restoreState()


def _paragraph_list(items: Iterable[str], style) -> list[Paragraph | Spacer]:
    story: list[Paragraph | Spacer] = []
    for item in items:
        story.append(Paragraph(f"- {item}", style))
        story.append(Spacer(1, 0.12 * cm))
    return story


def generate_auto_service_pdf(
    output_path: str | Path,
    summary_df: pd.DataFrame,
    service_df: pd.DataFrame,
    type_df: pd.DataFrame,
    channel_df: pd.DataFrame,
    department_df: pd.DataFrame,
    diagnostic: list[str],
    bottlenecks: list[str],
    odd_points: list[str],
    conclusion: str,
    recommendations: list[str],
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
        title="ANALISE DE AUTO SERVICO",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleCenter",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=23,
        leading=29,
        textColor=colors.HexColor("#12355B"),
    )
    subtitle = ParagraphStyle(
        "SubtitleCenter",
        parent=styles["Heading2"],
        alignment=TA_CENTER,
        fontSize=13,
        textColor=colors.HexColor("#344054"),
    )
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9, leading=12)

    story: list = [Spacer(1, 1.3 * cm)]
    if LOGO_PATH.exists():
        cover_logo = Image(str(LOGO_PATH), width=5.4 * cm, height=1.6 * cm)
        cover_logo.hAlign = "CENTER"
        story.extend([cover_logo, Spacer(1, 0.8 * cm)])
    story.extend(
        [
            Paragraph("ANALISE DE AUTO SERVICO", title),
            Spacer(1, 0.25 * cm),
            Paragraph("Mudanca de endereco + mudanca de comodo", subtitle),
            Spacer(1, 0.15 * cm),
            Paragraph("OS, faturas, CSAT, canais e departamentos", subtitle),
            PageBreak(),
            Paragraph("Resumo geral", styles["Heading2"]),
            _table(summary_df, font_size=8),
            Spacer(1, 0.5 * cm),
            Paragraph("Diagnostico principal", styles["Heading2"]),
            *_paragraph_list(diagnostic, body),
            PageBreak(),
            Paragraph("Mudanca de endereco x mudanca de comodo", styles["Heading2"]),
            _table(_compact_metric_table(service_df, "Servico"), font_size=7.0, max_rows=25, col_widths=[4.9 * cm, 1.8 * cm, 1.5 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 2.5 * cm, 2.0 * cm, 1.7 * cm, 1.7 * cm]),
            Spacer(1, 0.5 * cm),
            Paragraph("Autosservico x atendimento humano", styles["Heading2"]),
            _table(_compact_metric_table(type_df, "Tipo"), font_size=7.0, max_rows=25, col_widths=[4.9 * cm, 1.8 * cm, 1.5 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 2.5 * cm, 2.0 * cm, 1.7 * cm, 1.7 * cm]),
            PageBreak(),
            Paragraph("App Minha Valenet x WhatsApp", styles["Heading2"]),
            _table(_compact_metric_table(channel_df, "Canal"), font_size=7.0, max_rows=25, col_widths=[4.9 * cm, 1.8 * cm, 1.5 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 2.5 * cm, 2.0 * cm, 1.7 * cm, 1.7 * cm]),
            Spacer(1, 0.5 * cm),
            Paragraph("Analise por departamento/equipe", styles["Heading2"]),
            _table(_compact_metric_table(department_df, "Departamento"), font_size=6.8, max_rows=30, col_widths=[4.9 * cm, 1.8 * cm, 1.5 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 2.5 * cm, 2.0 * cm, 1.7 * cm, 1.7 * cm]),
            PageBreak(),
            Paragraph("Principais gargalos", styles["Heading2"]),
            *_paragraph_list(bottlenecks, body),
            Spacer(1, 0.4 * cm),
            Paragraph("Pontos estranhos da base", styles["Heading2"]),
            *_paragraph_list(odd_points, body),
            Spacer(1, 0.4 * cm),
            Paragraph("Conclusao", styles["Heading2"]),
            Paragraph(conclusion, body),
            PageBreak(),
            Paragraph("Acoes recomendadas", styles["Heading2"]),
            *_paragraph_list(recommendations, body),
        ]
    )

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf_bytes = buffer.getvalue()
    output_path.write_bytes(pdf_bytes)
    return pdf_bytes
