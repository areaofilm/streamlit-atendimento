from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .tratamento_tempo import format_seconds


def _bar(df: pd.DataFrame, x: str, y: str, title: str, color: str | None = None, text: str | None = None) -> go.Figure:
    fig = px.bar(df, x=x, y=y, color=color, barmode="group", text=text, title=title)
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(title_x=0.02, margin=dict(l=30, r=30, t=70, b=55), uniformtext_minsize=10, uniformtext_mode="hide")
    return fig


def create_d44_figures(
    status_df: pd.DataFrame,
    hsm_df: pd.DataFrame,
    proposal_df: pd.DataFrame,
    proposal_cross_df: pd.DataFrame,
    daily_df: pd.DataFrame,
) -> list[tuple[str, go.Figure]]:
    figures: list[tuple[str, go.Figure]] = []

    if not status_df.empty:
        figures.append(("Status dos atendimentos", _bar(status_df, "Status", "Volume", "Status dos atendimentos", text="Volume")))

    if not hsm_df.empty:
        hsm_focus = hsm_df[hsm_df["Opcao"].isin(["Pagar agora", "Preciso ajuda", "Nao respondeu"])].copy()
        figures.append(("HSM - Pagar agora x Preciso ajuda x Nao respondeu", _bar(hsm_focus, "Opcao", "Volume", "HSM - opcoes selecionadas", text="Volume")))

    if not proposal_df.empty:
        figures.append(("Resultado das propostas", _bar(proposal_df, "Resultado / proposta", "Volume", "Resultado das propostas", text="Volume")))
        proposal_plot = proposal_df.copy()
        proposal_plot["TMA (min)"] = proposal_plot["TMA"] / 60
        proposal_plot["TMA texto"] = proposal_plot["TMA"].apply(format_seconds)
        figures.append(("TMA por proposta", _bar(proposal_plot, "Resultado / proposta", "TMA (min)", "TMA por proposta", text="TMA texto")))

    if not proposal_cross_df.empty:
        figures.append(("Proposta x negociacao realizada", _bar(proposal_cross_df, "Grupo", "Negociacao realizada", "Proposta x negociacao realizada", text="Negociacao realizada")))

    if not status_df.empty:
        figures.append(("Inatividade por status", _bar(status_df, "Status", "Inatividade", "Inatividade por status", text="Inatividade")))

        status_rate = status_df[["Status", "Finalizados reais", "Inatividade"]].melt(id_vars="Status", var_name="Indicador", value_name="Volume")
        figures.append(("Finalizacao real x inatividade", _bar(status_rate, "Status", "Volume", "Finalizacao real x inatividade", color="Indicador", text="Volume")))

    if not daily_df.empty:
        figures.append(("Inatividade por dia", _bar(daily_df, "Data", "Inatividade", "Inatividade por dia", text="Inatividade")))
        figures.append(("Volume por dia", _bar(daily_df, "Data", "Volume", "Volume por dia", text="Volume")))
        daily_plot = daily_df.copy()
        daily_plot["TMA (min)"] = daily_plot["TMA"] / 60
        daily_plot["TMA texto"] = daily_plot["TMA"].apply(format_seconds)
        figures.append(("TMA por dia", _bar(daily_plot, "Data", "TMA (min)", "TMA por dia", text="TMA texto")))

    return figures

