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


def create_figures(
    comparison_df: pd.DataFrame,
    status_df: pd.DataFrame,
    type_df: pd.DataFrame,
    classification_df: pd.DataFrame,
    fee_df: pd.DataFrame,
) -> list[tuple[str, go.Figure]]:
    figures: list[tuple[str, go.Figure]] = []
    comparison_plot = comparison_df.copy()

    for column in ("TMA geral", "TME geral", "TMA sem inatividade"):
        comparison_plot[f"{column} (min)"] = comparison_plot[column] / 60
        comparison_plot[f"{column} texto"] = comparison_plot[column].apply(format_seconds)

    figures.append(
        (
            "TMA geral por mes",
            _bar(
                comparison_plot,
                "Mes",
                "TMA geral (min)",
                None,
                "TMA geral por mes",
                {"Mes": "Mes", "TMA geral (min)": "TMA medio (minutos)"},
                "TMA geral texto",
            ),
        )
    )
    figures.append(
        (
            "TME geral por mes",
            _bar(
                comparison_plot,
                "Mes",
                "TME geral (min)",
                None,
                "TME geral por mes",
                {"Mes": "Mes", "TME geral (min)": "TME medio (minutos)"},
                "TME geral texto",
            ),
        )
    )
    figures.append(
        (
            "TMA sem inatividade por mes",
            _bar(
                comparison_plot,
                "Mes",
                "TMA sem inatividade (min)",
                None,
                "TMA sem inatividade por mes",
                {"Mes": "Mes", "TMA sem inatividade (min)": "TMA medio sem inatividade (minutos)"},
                "TMA sem inatividade texto",
            ),
        )
    )

    status_plot = status_df.copy()
    if not status_plot.empty:
        figures.append(
            (
                "Status dos atendimentos",
                _bar(
                    status_plot,
                    "Status",
                    "Volume",
                    "Mes",
                    "Status dos atendimentos",
                    {"Status": "Status", "Volume": "Volume", "Mes": "Mes"},
                    "Volume",
                ),
            )
        )

    type_plot = type_df.copy()
    if not type_plot.empty:
        figures.append(
            (
                "Tipo de atendimento",
                _bar(
                    type_plot,
                    "Tipo",
                    "Volume",
                    "Mes",
                    "Tipo de atendimento",
                    {"Tipo": "Tipo", "Volume": "Volume", "Mes": "Mes"},
                    "Volume",
                ),
            )
        )

    class_plot = classification_df.copy()
    if not class_plot.empty:
        class_plot["Media (min)"] = class_plot["Media"] / 60
        class_plot["Media texto"] = class_plot["Media"].apply(format_seconds)
        figures.append(
            (
                "TMA por classificacao",
                _bar(
                    class_plot,
                    "Classificacao",
                    "Media (min)",
                    "Mes",
                    "TMA por classificacao",
                    {"Classificacao": "Classificacao", "Media (min)": "TMA medio (minutos)", "Mes": "Mes"},
                    "Media texto",
                ),
            )
        )
        figures.append(
            (
                "Inatividade por classificacao",
                _bar(
                    class_plot,
                    "Classificacao",
                    "Inatividade",
                    "Mes",
                    "Inatividade por classificacao",
                    {"Classificacao": "Classificacao", "Inatividade": "Inatividade", "Mes": "Mes"},
                    "Inatividade",
                ),
            )
        )

    fee_plot = fee_df.copy()
    if not fee_plot.empty:
        figures.append(
            (
                "Volume por identificacao de taxa",
                _bar(
                    fee_plot,
                    "Grupo",
                    "Volume",
                    "Mes",
                    "Volume por identificacao de taxa",
                    {"Grupo": "Grupo", "Volume": "Volume", "Mes": "Mes"},
                    "Volume",
                ),
            )
        )

    return figures
