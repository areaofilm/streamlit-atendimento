from __future__ import annotations

from html import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Table, TableStyle


HEADER_COLOR = colors.HexColor("#1F4E79")
GRID_COLOR = colors.HexColor("#D9E2F3")
ALT_ROW_COLOR = colors.HexColor("#F6F8FB")
TEXT_COLOR = colors.black
PDF_TABLE_WIDTH = 25.6 * cm
MIN_READABLE_FONT = 8.0


def _style(name: str, font_size: float, *, bold: bool = False, text_color=TEXT_COLOR) -> ParagraphStyle:
    return ParagraphStyle(
        name,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=font_size,
        leading=font_size + 2.2,
        textColor=text_color,
        alignment=TA_LEFT,
        wordWrap="CJK",
    )


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    text = "" if pd.isna(value) else str(value)
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _fit_col_widths(col_widths: list[float] | None, column_count: int, total_width: float) -> list[float] | None:
    if not col_widths:
        return None
    widths = list(col_widths[:column_count])
    if len(widths) < column_count:
        widths.extend([total_width / column_count] * (column_count - len(widths)))
    used_width = sum(widths)
    if used_width <= 0:
        return None
    scale = total_width / used_width
    return [width * scale for width in widths]


def _auto_col_widths(column_count: int, total_width: float = PDF_TABLE_WIDTH) -> list[float]:
    if column_count <= 0:
        return []
    if column_count == 1:
        return [total_width]
    if column_count == 2:
        return [total_width * 0.52, total_width * 0.48]
    if column_count <= 4:
        first = 7.0 * cm
    elif column_count <= 8:
        first = 5.8 * cm
    else:
        first = 4.9 * cm
    remaining = max(total_width - first, total_width * 0.55)
    return [first] + [remaining / (column_count - 1)] * (column_count - 1)


def readable_table(
    df: pd.DataFrame,
    font_size: float = MIN_READABLE_FONT,
    *,
    max_rows: int | None = None,
    col_widths: list[float] | None = None,
    total_width: float = PDF_TABLE_WIDTH,
    bold_first_column: bool = False,
) -> Table:
    if df.empty and len(df.columns) == 0:
        df = pd.DataFrame([{"Aviso": "Sem dados disponiveis para esta secao."}])
    shown = df.head(max_rows) if max_rows else df
    size = max(float(font_size), MIN_READABLE_FONT)
    header_style = _style("PdfTableHeader", size, bold=True, text_color=colors.white)
    body_style = _style("PdfTableBody", size)
    first_col_style = _style("PdfTableFirstColumn", size, bold=True)

    data: list[list[Paragraph]] = [[_paragraph(column, header_style) for column in shown.columns]]
    for row in shown.itertuples(index=False, name=None):
        data.append(
            [
                _paragraph(value, first_col_style if bold_first_column and index == 0 else body_style)
                for index, value in enumerate(row)
            ]
        )

    fitted_widths = _fit_col_widths(col_widths, len(shown.columns), total_width) or _auto_col_widths(len(shown.columns), total_width)
    table = Table(data, repeatRows=1, colWidths=fitted_widths, hAlign="CENTER")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_COLOR),
                ("GRID", (0, 0), (-1, -1), 0.25, GRID_COLOR),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW_COLOR]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def vertical_indicator_table(
    df: pd.DataFrame,
    *,
    indicator_header: str = "Indicador",
    value_header: str = "Valor",
    font_size: float = 8.5,
    total_width: float = 16.0 * cm,
) -> Table:
    if df.empty:
        return readable_table(pd.DataFrame([{"Aviso": "Sem dados disponiveis para esta secao."}]), font_size=font_size)

    if len(df.columns) == 2 and str(df.columns[0]).lower() in {"indicador", "item"}:
        vertical_df = df.rename(columns={df.columns[0]: indicator_header, df.columns[1]: value_header})
    else:
        row = df.iloc[0].to_dict()
        vertical_df = pd.DataFrame(
            [{indicator_header: str(key), value_header: str(value)} for key, value in row.items()]
        )

    return readable_table(
        vertical_df,
        font_size=font_size,
        col_widths=[8.5 * cm, 7.5 * cm],
        total_width=total_width,
        bold_first_column=True,
    )
