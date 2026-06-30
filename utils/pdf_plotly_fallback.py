from __future__ import annotations

from typing import Any

from plotly.graph_objects import Figure
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Flowable, Paragraph
from reportlab.lib.styles import getSampleStyleSheet


PALETTE = [
    colors.HexColor("#1F77B4"),
    colors.HexColor("#FF7F0E"),
    colors.HexColor("#2CA02C"),
    colors.HexColor("#D62728"),
    colors.HexColor("#9467BD"),
    colors.HexColor("#8C564B"),
]


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _labels(values: Any) -> list[str]:
    if values is None:
        return []
    return [str(value) for value in list(values)]


def _format_value(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}".replace(",", ".")
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}".replace(".", ",")


def plotly_bar_fallback(figure: Figure, title: str | None = None) -> Flowable:
    """Render a simple Plotly bar figure with ReportLab, avoiding Kaleido/Chrome."""

    traces = [trace for trace in figure.data if getattr(trace, "y", None) is not None]
    if not traces:
        return Paragraph("Grafico indisponivel: dados insuficientes para renderizacao alternativa.", getSampleStyleSheet()["BodyText"])

    categories = _labels(getattr(traces[0], "x", None))
    if not categories:
        categories = [str(index + 1) for index in range(len(list(traces[0].y)))]

    series: list[list[float]] = []
    names: list[str] = []
    for trace in traces[:6]:
        values = [_as_float(value) for value in list(trace.y)]
        if len(values) < len(categories):
            values.extend([0.0] * (len(categories) - len(values)))
        series.append(values[: len(categories)])
        names.append(str(getattr(trace, "name", "") or "Volume"))

    drawing_width = 25 * cm
    drawing_height = 12.9 * cm
    drawing = Drawing(drawing_width, drawing_height)
    drawing.add(String(0.2 * cm, drawing_height - 0.5 * cm, title or "", fontName="Helvetica-Bold", fontSize=12, fillColor=colors.HexColor("#111827")))

    chart = VerticalBarChart()
    chart.x = 1.0 * cm
    chart.y = 1.8 * cm
    chart.width = 22.8 * cm
    chart.height = 8.4 * cm
    chart.data = series
    chart.categoryAxis.categoryNames = [label[:22] for label in categories]
    chart.categoryAxis.labels.boxAnchor = "ne"
    chart.categoryAxis.labels.dx = -4
    chart.categoryAxis.labels.dy = -2
    chart.categoryAxis.labels.angle = 30
    chart.categoryAxis.labels.fontSize = 6
    chart.valueAxis.valueMin = 0
    max_value = max((max(values) for values in series if values), default=0)
    chart.valueAxis.valueMax = max(1, max_value * 1.35)
    chart.valueAxis.labels.fontSize = 7
    chart.bars.strokeColor = colors.white
    for index, color in enumerate(PALETTE):
        if index < len(series):
            chart.bars[index].fillColor = color
    drawing.add(chart)

    category_count = max(len(categories), 1)
    series_count = max(len(series), 1)
    group_width = chart.width / category_count
    bar_width = group_width * 0.72 / series_count
    group_padding = group_width * 0.14
    value_max = chart.valueAxis.valueMax or 1
    for series_index, values in enumerate(series):
        for category_index, value in enumerate(values):
            if value <= 0:
                continue
            x = chart.x + category_index * group_width + group_padding + series_index * bar_width + (bar_width / 2)
            y = chart.y + (value / value_max) * chart.height + 0.06 * cm
            drawing.add(
                String(
                    x,
                    min(y, chart.y + chart.height + 0.15 * cm),
                    _format_value(value),
                    textAnchor="middle",
                    fontName="Helvetica-Bold",
                    fontSize=9,
                    fillColor=colors.HexColor("#111827"),
                )
            )

    if len(series) > 1:
        legend = Legend()
        legend.x = 1.0 * cm
        legend.y = 0.6 * cm
        legend.fontSize = 7
        legend.colorNamePairs = [(PALETTE[index % len(PALETTE)], name[:28]) for index, name in enumerate(names)]
        drawing.add(legend)

    return drawing
