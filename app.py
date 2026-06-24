from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from utils.analise_atendimento import (
    analyze_month,
    automatic_conclusion,
    build_group_dataframe,
    build_summary_dataframe,
    detect_columns,
    format_group_dataframe,
    format_summary_dataframe,
    textual_columns_warning,
)
from utils.graficos import create_figures
from utils.leitura_csv import CsvReadError, read_csv_flexible, readable_column_options
from utils.pdf_report import generate_pdf
from utils.tratamento_tempo import format_seconds


APP_DIR = Path(__file__).resolve().parent
REPORT_DIR = APP_DIR / "output"


st.set_page_config(
    page_title="Analise comparativa de atendimento",
    page_icon=":bar_chart:",
    layout="wide",
)


st.markdown(
    """
    <style>
    .main .block-container { padding-top: 1.5rem; max-width: 1320px; }
    div[data-testid="stMetric"] {
        background: #f8fafc;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 14px 16px;
    }
    .section-title {
        margin-top: 1.25rem;
        padding-top: .75rem;
        border-top: 1px solid #e5e7eb;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _safe_read(uploaded_file):
    if uploaded_file is None:
        return None, None
    try:
        result = read_csv_flexible(uploaded_file)
        return result, None
    except CsvReadError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 - shown as friendly Streamlit error.
        return None, f"Erro inesperado ao ler o arquivo: {exc}"


def _select_index(options: list[str], selected: str | None) -> int:
    if selected and selected in options:
        return options.index(selected)
    return 0


def _column_controls(df: pd.DataFrame, detected: dict, key_prefix: str) -> dict:
    columns = readable_column_options(df.columns)
    required_options = [""] + columns
    wait_options = ["Usar TME = 0"] + columns

    tma_default = detected.get("attendance_time")
    wait_default = detected.get("wait_time")
    status_default = detected.get("status")
    text_default = detected.get("text_columns") or []

    attendance_time_col = st.selectbox(
        "Coluna de tempo de atendimento (TMA)",
        required_options,
        index=_select_index(required_options, tma_default),
        key=f"{key_prefix}_tma",
        help="Obrigatoria para calcular TMA e mediana de TMA.",
    )
    wait_time_col = st.selectbox(
        "Coluna de tempo de espera/fila (TME)",
        wait_options,
        index=_select_index(wait_options, wait_default),
        key=f"{key_prefix}_tme",
        help="Se nao existir no arquivo, mantenha TME = 0.",
    )
    status_col = st.selectbox(
        "Coluna de status",
        required_options,
        index=_select_index(required_options, status_default),
        key=f"{key_prefix}_status",
    )
    text_columns = st.multiselect(
        "Campos textuais para identificar mudanca e taxa",
        columns,
        default=[col for col in text_default if col in columns],
        key=f"{key_prefix}_text",
        help="Use tags, classificacao, assunto, servico, motivo, fila e categoria quando existirem.",
    )

    warning = textual_columns_warning(text_columns)
    if warning:
        st.warning(warning)

    return {
        "attendance_time_col": attendance_time_col or None,
        "wait_time_col": None if wait_time_col == "Usar TME = 0" else wait_time_col,
        "status_col": status_col or None,
        "text_columns": text_columns,
    }


def _render_metrics(analyses) -> None:
    cols = st.columns(4)
    total_file = sum(item.total_file for item in analyses)
    total_change = sum(item.total_change for item in analyses)
    total_inactivity = sum(item.general_inactivity for item in analyses)
    avg_tma = sum(item.general_tma_seconds for item in analyses) / len(analyses)

    cols[0].metric("Total nos arquivos", f"{total_file:,}".replace(",", "."))
    cols[1].metric("Total no recorte", f"{total_change:,}".replace(",", "."))
    cols[2].metric("Inatividade geral", f"{total_inactivity:,}".replace(",", "."))
    cols[3].metric("TMA medio geral", format_seconds(avg_tma))


def _render_analysis(results: dict) -> None:
    analyses = results["analyses"]
    summary_df = results["summary_df"]
    group_df = results["group_df"]
    formatted_summary = results["formatted_summary"]
    formatted_group = results["formatted_group"]
    figures = results["figures"]
    conclusion = results["conclusion"]
    months = results["months"]

    st.markdown('<div class="section-title"></div>', unsafe_allow_html=True)
    st.subheader("Indicadores principais")
    _render_metrics(analyses)

    st.subheader("Tabelas comparativas")
    st.caption("Resumo geral dos meses")
    st.dataframe(formatted_summary, use_container_width=True, hide_index=True)
    st.caption("Recorte com taxa / sem taxa / sem identificacao")
    st.dataframe(formatted_group, use_container_width=True, hide_index=True)

    st.subheader("Graficos comparativos")
    for title, figure in figures:
        st.plotly_chart(figure, use_container_width=True)

    st.subheader("Conclusao automatica")
    st.info(conclusion)

    st.subheader("Relatorio em PDF")
    if st.button("Gerar PDF", type="primary"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORT_DIR / f"relatorio_atendimento_{timestamp}.pdf"
        pdf_bytes = generate_pdf(
            output_path=output_path,
            months=months,
            summary_df=formatted_summary,
            group_df=formatted_group,
            figures=figures,
            conclusion=conclusion,
        )
        st.session_state["pdf_bytes"] = pdf_bytes
        st.session_state["pdf_name"] = output_path.name
        st.session_state["pdf_path"] = str(output_path)
        st.success(f"PDF gerado e salvo localmente em: {output_path}")

    if st.session_state.get("pdf_bytes"):
        st.download_button(
            "Baixar PDF",
            data=st.session_state["pdf_bytes"],
            file_name=st.session_state.get("pdf_name", "relatorio_atendimento.pdf"),
            mime="application/pdf",
        )


st.title("Analise comparativa de relatorios CSV de atendimento")
st.caption("Mudanca de Endereco + Mudanca de Comodo | TMA, TME, inatividade e taxa")

left, right = st.columns(2)
with left:
    st.subheader("Mes 1")
    month_1 = st.text_input("Nome do mes 1", value="Maio")
    upload_1 = st.file_uploader("CSV do mes 1", type=["csv"], key="upload_1")
with right:
    st.subheader("Mes 2")
    month_2 = st.text_input("Nome do mes 2", value="Junho")
    upload_2 = st.file_uploader("CSV do mes 2", type=["csv"], key="upload_2")

result_1, error_1 = _safe_read(upload_1)
result_2, error_2 = _safe_read(upload_2)

if error_1:
    st.error(f"Mes 1: {error_1}")
if error_2:
    st.error(f"Mes 2: {error_2}")

controls_1 = controls_2 = None
if result_1:
    st.success(
        f"Mes 1 carregado: {len(result_1.dataframe)} linhas, {len(result_1.dataframe.columns)} colunas "
        f"(encoding {result_1.encoding}, separador {result_1.separator})."
    )
if result_2:
    st.success(
        f"Mes 2 carregado: {len(result_2.dataframe)} linhas, {len(result_2.dataframe.columns)} colunas "
        f"(encoding {result_2.encoding}, separador {result_2.separator})."
    )

if result_1 and result_2:
    st.subheader("Mapeamento de colunas")
    col_map_1, col_map_2 = st.columns(2)
    with col_map_1:
        st.markdown(f"**{month_1}**")
        controls_1 = _column_controls(result_1.dataframe, detect_columns(result_1.dataframe), "m1")
    with col_map_2:
        st.markdown(f"**{month_2}**")
        controls_2 = _column_controls(result_2.dataframe, detect_columns(result_2.dataframe), "m2")

analyze_clicked = st.button("Analisar", type="primary", use_container_width=True)

if analyze_clicked:
    st.session_state.pop("pdf_bytes", None)
    if not upload_1 or not upload_2:
        st.warning("Envie os dois arquivos CSV para iniciar a analise.")
    elif not result_1 or not result_2:
        st.error("Corrija os erros de leitura dos arquivos antes de analisar.")
    elif not controls_1 or not controls_2:
        st.error("Confira o mapeamento das colunas antes de analisar.")
    elif not controls_1["attendance_time_col"] or not controls_2["attendance_time_col"]:
        st.error("Selecione a coluna de tempo de atendimento (TMA) para os dois meses.")
    else:
        try:
            analysis_1 = analyze_month(result_1.dataframe, month_1, **controls_1)
            analysis_2 = analyze_month(result_2.dataframe, month_2, **controls_2)
            analyses = [analysis_1, analysis_2]
            summary_df = build_summary_dataframe(analyses)
            group_df = build_group_dataframe(analyses)
            figures = create_figures(summary_df, group_df)
            st.session_state["analysis_results"] = {
                "analyses": analyses,
                "summary_df": summary_df,
                "group_df": group_df,
                "formatted_summary": format_summary_dataframe(summary_df),
                "formatted_group": format_group_dataframe(group_df),
                "figures": figures,
                "conclusion": automatic_conclusion(analyses, group_df),
                "months": (month_1, month_2),
            }
        except Exception as exc:  # noqa: BLE001 - keep UI friendly.
            st.error(f"Nao foi possivel concluir a analise: {exc}")

if st.session_state.get("analysis_results"):
    _render_analysis(st.session_state["analysis_results"])
