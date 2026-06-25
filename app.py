from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from utils.analise_atendimento import (
    LOW_VOLUME_MESSAGE,
    LOW_VOLUME_THRESHOLD,
    FILTER_ALL,
    FILTER_CHANGE,
    FILTER_CUSTOM,
    analyze_month,
    automatic_conclusion,
    build_bottleneck_dataframe,
    build_classification_dataframe,
    build_comparison_dataframe,
    build_executive_summary,
    build_fee_dataframe,
    build_period_dataframe,
    build_status_dataframe,
    build_type_dataframe,
    comparison_reliability,
    detect_columns,
    format_comparison_dataframe,
    format_bottleneck_dataframe,
    format_fee_dataframe,
    format_metric_dataframe,
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
    .health-card {
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 14px 16px;
        background: #f8fafc;
        min-height: 108px;
    }
    .health-green { border-left: 7px solid #16a34a; }
    .health-yellow { border-left: 7px solid #f59e0b; }
    .health-red { border-left: 7px solid #dc2626; }
    .health-card small { color: #475467; }
    .health-card strong { font-size: 1rem; color: #111827; }
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


def _parse_terms(text: str) -> list[str]:
    terms: list[str] = []
    for line in text.replace(";", "\n").replace(",", "\n").splitlines():
        clean = line.strip()
        if clean:
            terms.append(clean)
    return terms


def _traffic_color(kind: str, value: float | int | str) -> str:
    if kind == "inactivity":
        return "red" if float(value) >= 30 else "yellow" if float(value) >= 15 else "green"
    if kind == "finalization":
        return "red" if float(value) < 60 else "yellow" if float(value) < 80 else "green"
    if kind == "volume":
        return "red" if int(value) < 30 else "yellow" if int(value) < 50 else "green"
    if kind == "reliability":
        return "green" if value == "Comparacao confiavel" else "yellow" if value == "Comparacao parcial" else "red"
    return "green"


def _health_card(title: str, value: str, detail: str, color: str) -> str:
    return (
        f'<div class="health-card health-{color}">'
        f"<small>{title}</small><br><strong>{value}</strong><br><small>{detail}</small>"
        "</div>"
    )


def _build_excel_bytes(results: dict) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        results["executive_df"].to_excel(writer, sheet_name="Resumo Executivo", index=False)
        results["period_df"].to_excel(writer, sheet_name="Periodo", index=False)
        results["comparison_df"].to_excel(writer, sheet_name="Comparacao", index=False)
        results["status_df"].to_excel(writer, sheet_name="Status", index=False)
        results["type_df"].to_excel(writer, sheet_name="Tipo", index=False)
        results["classification_df"].to_excel(writer, sheet_name="Classificacao", index=False)
        results["fee_df"].to_excel(writer, sheet_name="Taxa", index=False)
        results["bottleneck_df"].to_excel(writer, sheet_name="Top Gargalos", index=False)
        filtered_base = _filtered_base_dataframe(results["analyses"])
        if not filtered_base.empty:
            filtered_base.to_excel(writer, sheet_name="Base Filtrada", index=False)
    return output.getvalue()


def _filtered_base_dataframe(analyses) -> pd.DataFrame:
    base_rows = []
    audit_cols = {
        "_grupo_taxa": "Grupo taxa",
        "_inatividade": "Inatividade",
        "_finalizado_real": "Finalizado real",
        "_tma_seconds": "TMA segundos",
        "_tme_seconds": "TME segundos",
    }
    for analysis in analyses:
        data = analysis.filtered_data.copy()
        original_cols = [col for col in data.columns if not str(col).startswith("_")]
        keep_cols = original_cols + [col for col in audit_cols if col in data.columns]
        exported = data[keep_cols].rename(columns=audit_cols)
        exported.insert(0, "Mes analisado", analysis.month)
        base_rows.append(exported)
    return pd.concat(base_rows, ignore_index=True) if base_rows else pd.DataFrame()


def _column_controls(df: pd.DataFrame, detected: dict, key_prefix: str) -> dict:
    columns = readable_column_options(df.columns)
    required_options = [""] + columns
    wait_options = ["Usar TME = 0"] + columns

    tma_default = detected.get("attendance_time")
    wait_default = detected.get("wait_time")
    status_default = detected.get("status")
    type_default = detected.get("type")
    classification_default = detected.get("classification")
    date_default = detected.get("date")
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
    type_col = st.selectbox(
        "Coluna de tipo de atendimento",
        required_options,
        index=_select_index(required_options, type_default),
        key=f"{key_prefix}_type",
        help="Exemplo: Humano, Misto ou Automatico.",
    )
    classification_col = st.selectbox(
        "Coluna de classificacao",
        required_options,
        index=_select_index(required_options, classification_default),
        key=f"{key_prefix}_classification",
    )
    date_col = st.selectbox(
        "Coluna de data de abertura/entrada",
        required_options,
        index=_select_index(required_options, date_default),
        key=f"{key_prefix}_date",
        help="Usada para exibir o periodo analisado.",
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
        "type_col": type_col or None,
        "classification_col": classification_col or None,
        "date_col": date_col or None,
        "text_columns": text_columns,
    }


def _render_metrics(analyses) -> None:
    cols = st.columns(4)
    total_change = sum(item.total_change for item in analyses)
    total_inactivity = sum(item.general_inactivity for item in analyses)
    avg_tma = sum(item.general_tma_seconds for item in analyses) / len(analyses)
    avg_tme = sum(item.general_tme_seconds for item in analyses) / len(analyses)

    cols[0].metric("Total no recorte", f"{total_change:,}".replace(",", "."))
    cols[1].metric("TMA medio", format_seconds(avg_tma))
    cols[2].metric("Inatividade geral", f"{total_inactivity:,}".replace(",", "."))
    cols[3].metric("TME medio", format_seconds(avg_tme))


def _render_analysis(results: dict) -> None:
    analyses = results["analyses"]
    executive_df = results["executive_df"]
    bottleneck_df = results["bottleneck_df"]
    formatted_comparison = results["formatted_comparison"]
    formatted_fee = results["formatted_fee"]
    formatted_period = results["formatted_period"]
    formatted_status = results["formatted_status"]
    formatted_type = results["formatted_type"]
    formatted_classification = results["formatted_classification"]
    formatted_bottleneck = results["formatted_bottleneck"]
    figures = results["figures"]
    conclusion = results["conclusion"]
    months = results["months"]

    st.markdown('<div class="section-title"></div>', unsafe_allow_html=True)
    st.subheader("Indicadores principais")
    _render_metrics(analyses)
    for analysis in analyses:
        if analysis.total_change < LOW_VOLUME_THRESHOLD:
            st.warning(f"{analysis.month}: {LOW_VOLUME_MESSAGE}")

    st.subheader("Diagnostico executivo")
    reliability, reliability_reason = comparison_reliability(analyses)
    card_cols = st.columns(4)
    total_volume = min(item.total_change for item in analyses) if analyses else 0
    max_inactivity = max((item.general_inactivity_pct for item in analyses), default=0)
    max_finalization = max(
        (
            row.get("% Finalizacao real", 0)
            for row in results["comparison_df"].to_dict("records")
        ),
        default=0,
    )
    card_cols[0].markdown(
        _health_card("Confiabilidade", reliability, reliability_reason, _traffic_color("reliability", reliability)),
        unsafe_allow_html=True,
    )
    card_cols[1].markdown(
        _health_card("Menor volume", str(total_volume), "Atendimentos no menor mes", _traffic_color("volume", total_volume)),
        unsafe_allow_html=True,
    )
    card_cols[2].markdown(
        _health_card("Pior inatividade", f"{max_inactivity:.1f}%", "Maior percentual entre os meses", _traffic_color("inactivity", max_inactivity)),
        unsafe_allow_html=True,
    )
    card_cols[3].markdown(
        _health_card("Melhor finalizacao real", f"{max_finalization:.1f}%", "Status exatamente Finalizado", _traffic_color("finalization", max_finalization)),
        unsafe_allow_html=True,
    )
    st.dataframe(executive_df, use_container_width=True, hide_index=True)

    st.subheader("Graficos comparativos")
    for title, figure in figures:
        st.plotly_chart(figure, use_container_width=True)

    st.subheader("Tabelas e auditoria")
    tab_summary, tab_tax, tab_bottlenecks, tab_data, tab_downloads = st.tabs(
        ["Resumo", "Taxa", "Top Gargalos", "Dados filtrados", "Downloads"]
    )
    with tab_summary:
        st.caption("Periodo e volume dos arquivos")
        st.dataframe(formatted_period, use_container_width=True, hide_index=True)
        st.caption("Comparacao principal de TMA, TME e inatividade")
        st.dataframe(formatted_comparison, use_container_width=True, hide_index=True)
        st.caption("Status dos atendimentos")
        st.dataframe(formatted_status, use_container_width=True, hide_index=True)
        st.caption("Tipo de atendimento")
        st.dataframe(formatted_type, use_container_width=True, hide_index=True)
        st.caption("Gargalo por classificacao")
        st.dataframe(formatted_classification, use_container_width=True, hide_index=True)
    with tab_tax:
        st.caption("TMA, TME e Inatividade por Taxa")
        st.dataframe(formatted_fee, use_container_width=True, hide_index=True)
    with tab_bottlenecks:
        st.caption("Top gargalos ordenados por inatividade e impacto estimado")
        st.dataframe(formatted_bottleneck, use_container_width=True, hide_index=True)
    with tab_data:
        filtered_base = _filtered_base_dataframe(analyses)
        st.dataframe(filtered_base, use_container_width=True, hide_index=True)
        st.download_button(
            "Baixar base filtrada em CSV",
            data=filtered_base.to_csv(index=False).encode("utf-8-sig"),
            file_name="base_filtrada_atendimentos.csv",
            mime="text/csv",
        )
    with tab_downloads:
        excel_bytes = _build_excel_bytes(results)
        st.download_button(
            "Baixar Excel da analise",
            data=excel_bytes,
            file_name="analise_atendimento.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.subheader("Conclusao automatica")
    st.info(conclusion)

    st.subheader("Relatorio em PDF")
    if st.button("Gerar PDF", type="primary"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORT_DIR / f"relatorio_atendimento_{timestamp}.pdf"
        try:
            with st.spinner("Gerando PDF. Aguarde alguns segundos enquanto os graficos sao renderizados..."):
                pdf_bytes = generate_pdf(
                    output_path=output_path,
                    months=months,
                    executive_df=executive_df,
                    period_df=formatted_period,
                    comparison_df=formatted_comparison,
                    status_df=formatted_status,
                    type_df=formatted_type,
                    classification_df=formatted_classification,
                    fee_df=formatted_fee,
                    bottleneck_df=formatted_bottleneck,
                    figures=figures,
                    conclusion=conclusion,
                )
            st.session_state["pdf_bytes"] = pdf_bytes
            st.session_state["pdf_name"] = output_path.name
            st.session_state["pdf_path"] = str(output_path)
            st.success(f"PDF gerado e salvo localmente em: {output_path}")
        except Exception as exc:  # noqa: BLE001 - keep the UI actionable.
            st.error(f"Nao foi possivel gerar o PDF: {exc}")

    if st.session_state.get("pdf_bytes"):
        st.download_button(
            "Baixar PDF",
            data=st.session_state["pdf_bytes"],
            file_name=st.session_state.get("pdf_name", "relatorio_atendimento.pdf"),
            mime="application/pdf",
        )


st.title("Analise comparativa de relatorios CSV de atendimento")
st.caption("Mudanca de Endereco + Mudanca de Comodo | TMA, TME, status, classificacao e contagem de taxa")

st.sidebar.header("Regras da analise")
filter_label = st.sidebar.radio(
    "Recorte analisado",
    ["Mudanca de Endereco + Mudanca de Comodo", "Arquivo inteiro", "Busca personalizada"],
)
filter_mode = {
    "Mudanca de Endereco + Mudanca de Comodo": FILTER_CHANGE,
    "Arquivo inteiro": FILTER_ALL,
    "Busca personalizada": FILTER_CUSTOM,
}[filter_label]
custom_filter_text = st.sidebar.text_area(
    "Termos da busca personalizada",
    value="",
    help="Use um termo por linha. Exemplo: cancelamento, renovacao, agendamento.",
)
with_fee_text = st.sidebar.text_area(
    "Termos extras para Com taxa",
    value="",
    help="Opcional. Use um termo por linha quando houver marcacoes especificas no seu CSV.",
)
without_fee_text = st.sidebar.text_area(
    "Termos extras para Sem taxa",
    value="",
    help="Opcional. Use um termo por linha quando houver marcacoes especificas no seu CSV.",
)
filter_terms = _parse_terms(custom_filter_text)
with_fee_terms = _parse_terms(with_fee_text)
without_fee_terms = _parse_terms(without_fee_text)

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
            if filter_mode == FILTER_CUSTOM and not filter_terms:
                st.error("Informe pelo menos um termo para usar a busca personalizada.")
                st.stop()
            analysis_1 = analyze_month(
                result_1.dataframe,
                month_1,
                **controls_1,
                filter_mode=filter_mode,
                filter_terms=filter_terms,
                with_fee_terms=with_fee_terms,
                without_fee_terms=without_fee_terms,
            )
            analysis_2 = analyze_month(
                result_2.dataframe,
                month_2,
                **controls_2,
                filter_mode=filter_mode,
                filter_terms=filter_terms,
                with_fee_terms=with_fee_terms,
                without_fee_terms=without_fee_terms,
            )
            analyses = [analysis_1, analysis_2]
            comparison_df = build_comparison_dataframe(analyses)
            period_df = build_period_dataframe(analyses)
            fee_df = build_fee_dataframe(analyses)
            status_df = build_status_dataframe(analyses)
            type_df = build_type_dataframe(analyses)
            classification_df = build_classification_dataframe(analyses)
            bottleneck_df = build_bottleneck_dataframe(classification_df)
            executive_df = build_executive_summary(analyses, status_df, classification_df)
            figures = create_figures(comparison_df, status_df, type_df, classification_df, fee_df)
            st.session_state["analysis_results"] = {
                "analyses": analyses,
                "executive_df": executive_df,
                "bottleneck_df": bottleneck_df,
                "comparison_df": comparison_df,
                "period_df": period_df,
                "fee_df": fee_df,
                "status_df": status_df,
                "type_df": type_df,
                "classification_df": classification_df,
                "formatted_comparison": format_comparison_dataframe(comparison_df),
                "formatted_period": period_df,
                "formatted_fee": format_fee_dataframe(fee_df),
                "formatted_status": format_metric_dataframe(status_df),
                "formatted_type": format_metric_dataframe(type_df),
                "formatted_classification": format_metric_dataframe(classification_df),
                "formatted_bottleneck": format_bottleneck_dataframe(bottleneck_df),
                "figures": figures,
                "conclusion": automatic_conclusion(analyses, status_df, classification_df),
                "months": (month_1, month_2),
            }
        except Exception as exc:  # noqa: BLE001 - keep UI friendly.
            st.error(f"Nao foi possivel concluir a analise: {exc}")

if st.session_state.get("analysis_results"):
    _render_analysis(st.session_state["analysis_results"])
