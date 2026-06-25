from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .tratamento_tempo import duration_to_seconds, format_seconds


LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "valenet_logo.png"


def _table(df: pd.DataFrame, font_size: int = 7, max_rows: int | None = None) -> Table:
    if df.empty and len(df.columns) == 0:
        df = pd.DataFrame([{"Aviso": "Sem dados disponiveis para esta secao."}])
    shown = df.head(max_rows) if max_rows else df
    data = [list(shown.columns)] + shown.astype(str).values.tolist()
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
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _footer(canvas, _doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(1.2 * cm, 0.8 * cm, f"Gerado em {datetime.now():%d/%m/%Y %H:%M}")
    if LOGO_PATH.exists():
        canvas.drawImage(str(LOGO_PATH), 25.2 * cm, 0.45 * cm, width=3.3 * cm, height=1.0 * cm, preserveAspectRatio=True, mask="auto")
    canvas.restoreState()


def _bar_image(df: pd.DataFrame, x: str, y: str, title: str, color: str = "#1F4E79") -> Image | Paragraph:
    try:
        if df.empty or x not in df.columns or y not in df.columns:
            return Paragraph("Grafico indisponivel: dados nao encontrados.", getSampleStyleSheet()["BodyText"])
        plot_df = df[[x, y]].copy()
        if "TMA" in title.upper():
            plot_df[y] = plot_df[y].apply(duration_to_seconds)
        else:
            plot_df[y] = pd.to_numeric(plot_df[y], errors="coerce").fillna(0)
        plot_df = plot_df.head(18)

        fig, ax = plt.subplots(figsize=(10.8, 4.6))
        ax.bar(plot_df[x].astype(str), plot_df[y], color=color)
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_ylabel(y)
        ax.tick_params(axis="x", rotation=35, labelsize=8)
        ax.grid(axis="y", alpha=0.25)
        for index, value in enumerate(plot_df[y]):
            label = format_seconds(value) if "TMA" in title.upper() else f"{int(value)}"
            ax.text(index, value, label, ha="center", va="bottom", fontsize=8)
        fig.tight_layout()
        buffer = BytesIO()
        fig.savefig(buffer, format="png", dpi=140)
        plt.close(fig)
        buffer.seek(0)
        return Image(buffer, width=24.5 * cm, height=10.2 * cm)
    except Exception as exc:  # noqa: BLE001 - the PDF must not fail because a chart backend is unavailable.
        return Paragraph(f"Nao foi possivel renderizar este grafico no PDF: {exc}", getSampleStyleSheet()["BodyText"])


def _stacked_image(df: pd.DataFrame, x: str, y_columns: list[str], title: str) -> Image | Paragraph:
    try:
        if df.empty or x not in df.columns or any(column not in df.columns for column in y_columns):
            return Paragraph("Grafico indisponivel: dados nao encontrados.", getSampleStyleSheet()["BodyText"])
        plot_df = df[[x] + y_columns].copy().head(18)
        for column in y_columns:
            plot_df[column] = pd.to_numeric(plot_df[column], errors="coerce").fillna(0)

        fig, ax = plt.subplots(figsize=(10.8, 4.6))
        bottom = None
        colors_map = ["#16a34a", "#dc2626", "#f59e0b"]
        for index, column in enumerate(y_columns):
            values = plot_df[column]
            ax.bar(plot_df[x].astype(str), values, bottom=bottom, label=column, color=colors_map[index % len(colors_map)])
            bottom = values if bottom is None else bottom + values
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.tick_params(axis="x", rotation=35, labelsize=8)
        ax.legend()
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        buffer = BytesIO()
        fig.savefig(buffer, format="png", dpi=140)
        plt.close(fig)
        buffer.seek(0)
        return Image(buffer, width=24.5 * cm, height=10.2 * cm)
    except Exception as exc:  # noqa: BLE001 - the PDF must not fail because a chart backend is unavailable.
        return Paragraph(f"Nao foi possivel renderizar este grafico no PDF: {exc}", getSampleStyleSheet()["BodyText"])


def generate_d44_pdf(
    output_path: str | Path,
    period: str,
    summary_df: pd.DataFrame,
    comparison_df: pd.DataFrame,
    status_df: pd.DataFrame,
    type_df: pd.DataFrame,
    classification_df: pd.DataFrame,
    hsm_df: pd.DataFrame,
    proposal_df: pd.DataFrame,
    proposal_cross_df: pd.DataFrame,
    charge_df: pd.DataFrame,
    daily_df: pd.DataFrame,
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
        title="Analise de Cobranca HSM D44",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TitleCenter", parent=styles["Title"], alignment=TA_CENTER, fontSize=22, leading=28, textColor=colors.HexColor("#12355B"))
    subtitle = ParagraphStyle("SubtitleCenter", parent=styles["Heading2"], alignment=TA_CENTER, fontSize=13, textColor=colors.HexColor("#344054"))

    story = [
        Spacer(1, 2.0 * cm),
        Paragraph("Analise de Cobranca HSM D44", title),
        Spacer(1, 0.25 * cm),
        Paragraph(f"Periodo analisado: {period}", subtitle),
        PageBreak(),
        Paragraph("Resumo executivo", styles["Heading2"]),
        _table(summary_df, font_size=5),
        Spacer(1, 0.4 * cm),
    ]

    if not comparison_df.empty and len(comparison_df) > 1:
        story.extend([Paragraph("Comparacao principal", styles["Heading2"]), _table(comparison_df, font_size=5), Spacer(1, 0.4 * cm)])

    story.extend(
        [
            Paragraph("Conclusao automatica", styles["Heading2"]),
            Paragraph(conclusion, styles["BodyText"]),
            PageBreak(),
            Paragraph("Status dos atendimentos", styles["Heading2"]),
            _table(status_df, font_size=6, max_rows=25),
            Spacer(1, 0.4 * cm),
            Paragraph("Tipo de atendimento", styles["Heading2"]),
            _table(type_df, font_size=6, max_rows=20),
            PageBreak(),
            Paragraph("Classificacao", styles["Heading2"]),
            _table(classification_df, font_size=5, max_rows=25),
            PageBreak(),
            Paragraph("HSM - Opcao selecionada", styles["Heading2"]),
            _table(hsm_df, font_size=6),
            Spacer(1, 0.4 * cm),
            Paragraph("Resultado das propostas", styles["Heading2"]),
            _table(proposal_df, font_size=5),
            PageBreak(),
            Paragraph("Proposta x negociacao", styles["Heading2"]),
            _table(proposal_cross_df, font_size=6),
            Spacer(1, 0.4 * cm),
            Paragraph("Tags de cobranca", styles["Heading2"]),
            _table(charge_df, font_size=5, max_rows=25),
            PageBreak(),
            Paragraph("Analise por dia", styles["Heading2"]),
            _table(daily_df, font_size=5, max_rows=30),
            PageBreak(),
        ]
    )

    graph_specs = [
        ("Status dos atendimentos", _bar_image(status_df, "Status", "Volume", "Status dos atendimentos")),
        ("HSM - opcoes selecionadas", _bar_image(hsm_df[hsm_df.get("Opcao", pd.Series(dtype=str)).isin(["Pagar agora", "Preciso ajuda", "Nao respondeu"])] if not hsm_df.empty else hsm_df, "Opcao", "Volume", "HSM - opcoes selecionadas")),
        ("Resultado das propostas", _bar_image(proposal_df, "Resultado / proposta", "Volume", "Resultado das propostas")),
        ("Proposta x negociacao realizada", _bar_image(proposal_cross_df, "Grupo", "Negociacao realizada", "Proposta x negociacao realizada")),
        ("Inatividade por status", _bar_image(status_df, "Status", "Inatividade", "Inatividade por status", color="#dc2626")),
        ("Inatividade por dia", _bar_image(daily_df, "Data", "Inatividade", "Inatividade por dia", color="#dc2626")),
        ("Volume por dia", _bar_image(daily_df, "Data", "Volume", "Volume por dia")),
        ("TMA por dia", _bar_image(daily_df, "Data", "TMA", "TMA por dia")),
        ("TMA por proposta", _bar_image(proposal_df, "Resultado / proposta", "TMA", "TMA por proposta")),
        ("Finalizacao real x inatividade", _stacked_image(status_df, "Status", ["Finalizados reais", "Inatividade"], "Finalizacao real x inatividade")),
    ]

    for index, (title_text, image) in enumerate(graph_specs, start=1):
        story.append(Paragraph(title_text, styles["Heading2"]))
        story.append(image)
        if index % 2 == 0 and index != len(graph_specs):
            story.append(PageBreak())
        else:
            story.append(Spacer(1, 0.35 * cm))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf_bytes = buffer.getvalue()
    output_path.write_bytes(pdf_bytes)
    return pdf_bytes
