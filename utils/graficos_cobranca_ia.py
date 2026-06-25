from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .tratamento_tempo import format_seconds


def _bar(df: pd.DataFrame, x: str, y: str, title: str, color: str | None = None, text: str | None = None) -> go.Figure:
    fig = px.bar(df, x=x, y=y, color=color, barmode="group", text=text, title=title)
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(title_x=0.02, margin=dict(l=30, r=30, t=70, b=45), uniformtext_minsize=10, uniformtext_mode="hide")
    return fig


def create_charge_ai_figures(
    status_df: pd.DataFrame,
    type_df: pd.DataFrame,
    ia_df: pd.DataFrame,
    charge_df: pd.DataFrame,
    classification_df: pd.DataFrame,
    daily_df: pd.DataFrame,
) -> list[tuple[str, go.Figure]]:
    figures: list[tuple[str, go.Figure]] = []

    if not status_df.empty:
        figures.append(("Status dos atendimentos", _bar(status_df, "Status", "Volume", "Status dos atendimentos", text="Volume")))
    if not type_df.empty:
        figures.append(("Tipo de atendimento", _bar(type_df, "Tipo", "Volume", "Tipo de atendimento", text="Volume")))
    if not ia_df.empty:
        figures.append(("Principais tags da IA Velma", _bar(ia_df, "Tag IA Velma", "Volume", "Principais tags da IA Velma", text="Volume")))
    if not charge_df.empty:
        figures.append(("Principais tags de cobranca", _bar(charge_df, "Tag cobranca", "Volume", "Principais tags de cobranca", text="Volume")))
    if not classification_df.empty:
        figures.append(
            (
                "Inatividade por classificacao",
                _bar(classification_df, "Classificacao", "Inatividade", "Inatividade por classificacao", text="Inatividade"),
            )
        )
        class_plot = classification_df.copy()
        class_plot["TMA (min)"] = class_plot["TMA"] / 60
        class_plot["TMA texto"] = class_plot["TMA"].apply(format_seconds)
        figures.append(("TMA por classificacao", _bar(class_plot, "Classificacao", "TMA (min)", "TMA por classificacao", text="TMA texto")))
    if not daily_df.empty:
        figures.append(("Volume por dia", _bar(daily_df, "Data", "Volume", "Volume por dia", text="Volume")))
        figures.append(("Inatividade por dia", _bar(daily_df, "Data", "Inatividade", "Inatividade por dia", text="Inatividade")))

    return figures
