from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .tratamento_tempo import format_seconds


def _bar(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str | None,
    title: str,
    labels: dict[str, str],
    text: str | None = None,
) -> go.Figure:
    fig = px.bar(df, x=x, y=y, color=color, barmode="group", text=text, labels=labels, title=title)
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(
        title_x=0.02,
        legend_title_text=color if color else "",
        margin=dict(l=30, r=30, t=70, b=45),
        yaxis_title=labels.get(y, y),
        xaxis_title=labels.get(x, x),
        uniformtext_minsize=10,
        uniformtext_mode="hide",
    )
    return fig


def create_figures(summary_df: pd.DataFrame, group_df: pd.DataFrame) -> list[tuple[str, go.Figure]]:
    figures: list[tuple[str, go.Figure]] = []
    group_plot = group_df.copy()
    summary_plot = summary_df.copy()

    for column in ("TMA", "TME"):
        group_plot[f"{column} (min)"] = group_plot[column] / 60
        group_plot[f"{column} texto"] = group_plot[column].apply(format_seconds)

    figures.append(
        (
            "TMA por mes e grupo de taxa",
            _bar(
                group_plot,
                "Mes",
                "TMA (min)",
                "Grupo",
                "TMA por mes e grupo de taxa",
                {"Mes": "Mes", "TMA (min)": "TMA medio (minutos)", "Grupo": "Grupo"},
                "TMA texto",
            ),
        )
    )
    figures.append(
        (
            "TME por mes e grupo de taxa",
            _bar(
                group_plot,
                "Mes",
                "TME (min)",
                "Grupo",
                "TME por mes e grupo de taxa",
                {"Mes": "Mes", "TME (min)": "TME medio (minutos)", "Grupo": "Grupo"},
                "TME texto",
            ),
        )
    )
    figures.append(
        (
            "Volume por mes e grupo de taxa",
            _bar(
                group_plot,
                "Mes",
                "Volume",
                "Grupo",
                "Volume por mes e grupo de taxa",
                {"Mes": "Mes", "Volume": "Volume", "Grupo": "Grupo"},
                "Volume",
            ),
        )
    )
    figures.append(
        (
            "Inatividade por mes e grupo de taxa",
            _bar(
                group_plot,
                "Mes",
                "Inatividade",
                "Grupo",
                "Inatividade por mes e grupo de taxa",
                {"Mes": "Mes", "Inatividade": "Quantidade de inatividade", "Grupo": "Grupo"},
                "Inatividade",
            ),
        )
    )
    figures.append(
        (
            "Percentual de inatividade geral do mes",
            _bar(
                summary_plot,
                "Mes",
                "% inatividade geral",
                None,
                "Percentual de inatividade geral do mes",
                {"Mes": "Mes", "% inatividade geral": "% inatividade geral"},
                "% inatividade geral",
            ),
        )
    )
    figures.append(
        (
            "Total do recorte mudanca endereco + comodo por mes",
            _bar(
                summary_plot,
                "Mes",
                "Total mudanca endereco + comodo",
                None,
                "Total do recorte mudanca endereco + comodo por mes",
                {"Mes": "Mes", "Total mudanca endereco + comodo": "Total do recorte"},
                "Total mudanca endereco + comodo",
            ),
        )
    )

    return figures

