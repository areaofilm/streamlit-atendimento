from __future__ import annotations

import json
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
from utils.analise_autosservico import (
    analyze_auto_service,
    detect_auto_service_columns,
    format_auto_service_table,
    format_money,
    format_number,
    format_percent,
    read_auto_service_file,
)
from utils.analise_cobranca_ia import (
    analyze_charge_ai,
    detect_charge_ai_columns,
    format_charge_summary,
    format_metric_table,
    format_tag_table,
)
from utils.analise_cobranca_hsm_d44 import (
    LOW_D44_VOLUME_MESSAGE,
    LOW_D44_VOLUME_THRESHOLD,
    analyze_d44,
    build_d44_comparison_dataframe,
    combine_rows,
    detect_d44_columns,
    format_d44_metric_table,
    format_d44_summary,
)
from utils.auditoria_os_pro import (
    DEFAULT_CRITERIA_JSON,
    analyze_os_pro,
    analyze_with_ai,
    diagnose_openai_key,
    parse_criteria_document,
    parse_criteria_json,
    read_uploaded_text,
    result_to_tables,
)
from utils.graficos import create_figures
from utils.graficos_cobranca_ia import create_charge_ai_figures
from utils.graficos_cobranca_hsm_d44 import create_d44_figures
from utils.leitura_csv import CsvReadError, read_csv_flexible, readable_column_options
from utils.pdf_cobranca_ia import generate_charge_ai_pdf
from utils.pdf_cobranca_hsm_d44 import generate_d44_pdf
from utils.pdf_autosservico import generate_auto_service_pdf
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


def _build_charge_ai_excel_bytes(results: dict) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        results["summary_df"].to_excel(writer, sheet_name="Resumo", index=False)
        results["status_df"].to_excel(writer, sheet_name="Status", index=False)
        results["type_df"].to_excel(writer, sheet_name="Tipo", index=False)
        results["classification_df"].to_excel(writer, sheet_name="Classificacao", index=False)
        results["ia_df"].to_excel(writer, sheet_name="IA Velma", index=False)
        results["charge_df"].to_excel(writer, sheet_name="Cobranca", index=False)
        results["recurrence_df"].to_excel(writer, sheet_name="Recorrencia", index=False)
        results["daily_df"].to_excel(writer, sheet_name="Por Dia", index=False)
    return output.getvalue()


def _build_d44_excel_bytes(results: dict) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        results["summary_df"].to_excel(writer, sheet_name="Resumo Executivo D44", index=False)
        results["comparison_df"].to_excel(writer, sheet_name="Comparacao", index=False)
        results["status_df"].to_excel(writer, sheet_name="Status", index=False)
        results["type_df"].to_excel(writer, sheet_name="Tipo", index=False)
        results["classification_df"].to_excel(writer, sheet_name="Classificacao", index=False)
        results["hsm_df"].to_excel(writer, sheet_name="HSM Opcao", index=False)
        results["proposal_df"].to_excel(writer, sheet_name="Resultado Propostas", index=False)
        results["proposal_cross_df"].to_excel(writer, sheet_name="Proposta x Negociacao", index=False)
        results["charge_df"].to_excel(writer, sheet_name="Tags Cobranca", index=False)
        results["daily_df"].to_excel(writer, sheet_name="Por Dia", index=False)
        filtered = _d44_filtered_base_dataframe(results["analyses"])
        if not filtered.empty:
            filtered.to_excel(writer, sheet_name="Base D44", index=False)
    return output.getvalue()


def _d44_filtered_base_dataframe(analyses) -> pd.DataFrame:
    rows = []
    audit_cols = {
        "_hsm_opcao": "Opcao HSM",
        "_finalizado_real": "Finalizado real",
        "_inatividade": "Inatividade",
        "_pendente": "Pendente",
        "_transferido": "Transferido",
        "_tma_seconds": "TMA segundos",
        "_tme_seconds": "TME segundos",
        "_pending_seconds": "Pendencia segundos",
    }
    for analysis in analyses:
        data = analysis.prepared_data.copy()
        if data.empty:
            continue
        original_cols = [col for col in data.columns if not str(col).startswith("_")]
        keep_cols = original_cols + [col for col in audit_cols if col in data.columns]
        exported = data[keep_cols].rename(columns=audit_cols)
        exported.insert(0, "Mes analisado", analysis.month)
        rows.append(exported)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _render_d44_analysis(results: dict) -> None:
    analyses = results["analyses"]
    formatted_summary = results["formatted_summary"]
    formatted_comparison = results["formatted_comparison"]
    formatted_status = results["formatted_status"]
    formatted_type = results["formatted_type"]
    formatted_classification = results["formatted_classification"]
    formatted_hsm = results["formatted_hsm"]
    formatted_proposal = results["formatted_proposal"]
    formatted_proposal_cross = results["formatted_proposal_cross"]
    formatted_charge = results["formatted_charge"]
    formatted_daily = results["formatted_daily"]
    figures = results["figures"]
    conclusion = results["conclusion"]

    st.markdown('<div class="section-title"></div>', unsafe_allow_html=True)
    st.subheader("Analise de Cobranca HSM D44")

    for analysis in analyses:
        for warning in analysis.warnings:
            st.warning(f"{analysis.month}: {warning}")
        if analysis.total_d44 == 0:
            st.warning(f"{analysis.month}: Nenhum atendimento de Cobranca HSM D44 foi encontrado neste arquivo.")
        elif analysis.total_d44 < LOW_D44_VOLUME_THRESHOLD:
            st.warning(f"{analysis.month}: {LOW_D44_VOLUME_MESSAGE}")

    total_d44 = sum(item.summary_row.get("Total de atendimentos D44", 0) for item in analyses)
    total_file = sum(item.summary_row.get("Total de atendimentos no arquivo", 0) for item in analyses)
    total_inactivity = sum(item.summary_row.get("Finalizados por inatividade", 0) for item in analyses)
    total_finished = sum(item.summary_row.get("Finalizados reais", 0) for item in analyses)
    total_pending = sum(item.summary_row.get("Atendimento pendente", 0) for item in analyses)
    total_transferred = sum(item.summary_row.get("Transferidos", 0) for item in analyses)
    total_pagar = sum(item.summary_row.get("Pagar agora", 0) for item in analyses)
    total_ajuda = sum(item.summary_row.get("Preciso ajuda", 0) for item in analyses)
    total_no_answer = sum(item.summary_row.get("Nao respondeu", 0) for item in analyses)
    total_no_interest = sum(item.summary_row.get("Proposta sem juros", 0) for item in analyses)
    total_discount = sum(item.summary_row.get("Proposta com desconto", 0) for item in analyses)
    total_negotiation = sum(item.summary_row.get("Negociacao realizada", 0) for item in analyses)
    weighted_tma = (
        sum(item.summary_row.get("TMA geral", 0) * item.summary_row.get("Total de atendimentos D44", 0) for item in analyses) / total_d44
        if total_d44
        else 0
    )
    weighted_tme = (
        sum(item.summary_row.get("TME medio", 0) * item.summary_row.get("Total de atendimentos D44", 0) for item in analyses) / total_d44
        if total_d44
        else 0
    )
    weighted_tma_no_inactivity = (
        sum(item.summary_row.get("TMA sem inatividade", 0) * item.summary_row.get("Total de atendimentos D44", 0) for item in analyses) / total_d44
        if total_d44
        else 0
    )
    median_tma = analyses[0].summary_row.get("Mediana TMA", 0) if len(analyses) == 1 else results["comparison_df"]["Mediana TMA"].median()
    period_label = " | ".join(f"{item.month}: {item.period}" for item in analyses)

    metric_items = [
        ("Total D44", total_d44),
        ("Periodo", period_label),
        ("TMA geral", format_seconds(weighted_tma)),
        ("Mediana TMA", format_seconds(median_tma)),
        ("TMA sem inatividade", format_seconds(weighted_tma_no_inactivity)),
        ("TME geral", format_seconds(weighted_tme)),
        ("Finalizados reais", total_finished),
        ("% finalizacao real", f"{(total_finished / total_d44 * 100) if total_d44 else 0:.1f}%"),
        ("Inatividade", total_inactivity),
        ("% inatividade", f"{(total_inactivity / total_d44 * 100) if total_d44 else 0:.1f}%"),
        ("Pendentes", total_pending),
        ("Transferidos", total_transferred),
        ("Pagar agora", total_pagar),
        ("Preciso ajuda", total_ajuda),
        ("Nao respondeu", total_no_answer),
        ("Proposta sem juros", total_no_interest),
        ("Proposta com desconto", total_discount),
        ("Negociacao realizada", total_negotiation),
    ]
    for start in range(0, len(metric_items), 4):
        cols = st.columns(4)
        for col, (label, value) in zip(cols, metric_items[start : start + 4]):
            col.metric(label, value)

    st.subheader("Tabelas")
    tabs = st.tabs(
        [
            "Resumo",
            "Operacao",
            "HSM",
            "Propostas",
            "Tags e dia",
            "Downloads",
        ]
    )
    with tabs[0]:
        st.caption("Resumo executivo D44")
        st.dataframe(formatted_summary, use_container_width=True, hide_index=True)
        if len(analyses) > 1:
            st.caption("Comparacao principal")
            st.dataframe(formatted_comparison, use_container_width=True, hide_index=True)
        st.info(conclusion)
    with tabs[1]:
        st.caption("Status dos atendimentos")
        st.dataframe(formatted_status, use_container_width=True, hide_index=True)
        st.caption("Tipo de atendimento")
        st.dataframe(formatted_type, use_container_width=True, hide_index=True)
        st.caption("Classificacao")
        st.dataframe(formatted_classification, use_container_width=True, hide_index=True)
    with tabs[2]:
        st.caption("HSM - Opcao selecionada")
        st.dataframe(formatted_hsm, use_container_width=True, hide_index=True)
    with tabs[3]:
        st.caption("Resultado das propostas")
        st.dataframe(formatted_proposal, use_container_width=True, hide_index=True)
        st.caption("Proposta x negociacao")
        st.dataframe(formatted_proposal_cross, use_container_width=True, hide_index=True)
    with tabs[4]:
        st.caption("Tags de cobranca")
        st.dataframe(formatted_charge, use_container_width=True, hide_index=True)
        st.caption("Analise por dia")
        if formatted_daily.empty:
            st.warning("Coluna de data nao encontrada ou sem datas validas. Analise por dia nao gerada.")
        else:
            st.dataframe(formatted_daily, use_container_width=True, hide_index=True)
    with tabs[5]:
        st.download_button(
            "Baixar Excel da analise",
            data=_build_d44_excel_bytes(results),
            file_name="analise_cobranca_hsm_d44.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        filtered_base = _d44_filtered_base_dataframe(analyses)
        if not filtered_base.empty:
            st.download_button(
                "Baixar base D44 em CSV",
                data=filtered_base.to_csv(index=False).encode("utf-8-sig"),
                file_name="base_cobranca_hsm_d44.csv",
                mime="text/csv",
            )

    st.subheader("Graficos")
    for _title, figure in figures:
        st.plotly_chart(figure, use_container_width=True)

    st.subheader("Relatorio em PDF")
    if st.button("Gerar PDF", type="primary", key="d44_pdf"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORT_DIR / f"relatorio_cobranca_hsm_d44_{timestamp}.pdf"
        try:
            with st.spinner("Gerando PDF da analise de Cobranca HSM D44..."):
                pdf_bytes = generate_d44_pdf(
                    output_path=output_path,
                    period=period_label,
                    summary_df=formatted_summary,
                    comparison_df=formatted_comparison,
                    status_df=formatted_status,
                    type_df=formatted_type,
                    classification_df=formatted_classification,
                    hsm_df=formatted_hsm,
                    proposal_df=formatted_proposal,
                    proposal_cross_df=formatted_proposal_cross,
                    charge_df=formatted_charge,
                    daily_df=formatted_daily,
                    conclusion=conclusion,
                )
            st.session_state["d44_pdf_bytes"] = pdf_bytes
            st.session_state["d44_pdf_name"] = output_path.name
            st.success(f"PDF gerado e salvo localmente em: {output_path}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Nao foi possivel gerar o PDF: {exc}")

    if st.session_state.get("d44_pdf_bytes"):
        st.download_button(
            "Baixar PDF",
            data=st.session_state["d44_pdf_bytes"],
            file_name=st.session_state.get("d44_pdf_name", "relatorio_cobranca_hsm_d44.pdf"),
            mime="application/pdf",
            key="d44_pdf_download",
        )


def _render_charge_ai_analysis(results: dict) -> None:
    analysis = results["analysis"]
    formatted_summary = results["formatted_summary"]
    formatted_status = results["formatted_status"]
    formatted_type = results["formatted_type"]
    formatted_classification = results["formatted_classification"]
    formatted_ia = results["formatted_ia"]
    formatted_charge = results["formatted_charge"]
    formatted_recurrence = results["formatted_recurrence"]
    formatted_daily = results["formatted_daily"]
    figures = results["figures"]
    conclusion = results["conclusion"]

    st.markdown('<div class="section-title"></div>', unsafe_allow_html=True)
    st.subheader("Analise de Cobranca com IA")
    for warning in analysis.warnings:
        st.warning(warning)

    summary = analysis.summary_row
    metric_items = [
        ("Total de atendimentos", summary["Total de atendimentos"]),
        ("TMA geral", format_seconds(summary["TMA geral"])),
        ("Mediana TMA", format_seconds(summary["Mediana TMA"])),
        ("TME geral", format_seconds(summary["TME geral"])),
        ("Inatividade", summary["Finalizados por inatividade"]),
        ("% inatividade", f"{summary['% Inatividade']:.1f}%"),
        ("Transferidos", summary["Transferidos"]),
        ("% transferencia", f"{summary['% Transferencia']:.1f}%"),
        ("Finalizados reais", summary["Finalizados reais"]),
        ("% finalizacao real", f"{summary['% Finalizacao real']:.1f}%"),
        ("IA transferiu para agente", summary["IA transferiu para agente"]),
        ("Finalizado pela IA", summary["Finalizado pela IA"]),
        ("Erro API", summary["Erro API"]),
    ]
    for start in range(0, len(metric_items), 4):
        cols = st.columns(4)
        for col, (label, value) in zip(cols, metric_items[start : start + 4]):
            col.metric(label, value)

    st.subheader("Tabelas")
    tab_summary, tab_ia, tab_charge, tab_ops, tab_daily, tab_downloads = st.tabs(
        ["Resumo", "IA Velma", "Cobranca", "Operacao", "Por dia", "Downloads"]
    )
    with tab_summary:
        st.dataframe(formatted_summary, use_container_width=True, hide_index=True)
        st.info(conclusion)
    with tab_ia:
        st.dataframe(formatted_ia, use_container_width=True, hide_index=True)
    with tab_charge:
        st.dataframe(formatted_charge, use_container_width=True, hide_index=True)
        st.caption("Recorrencia")
        st.dataframe(formatted_recurrence, use_container_width=True, hide_index=True)
    with tab_ops:
        st.caption("Status dos atendimentos")
        st.dataframe(formatted_status, use_container_width=True, hide_index=True)
        st.caption("Tipo de atendimento")
        st.dataframe(formatted_type, use_container_width=True, hide_index=True)
        st.caption("Classificacao")
        st.dataframe(formatted_classification, use_container_width=True, hide_index=True)
    with tab_daily:
        st.dataframe(formatted_daily, use_container_width=True, hide_index=True)
    with tab_downloads:
        st.download_button(
            "Baixar Excel da analise",
            data=_build_charge_ai_excel_bytes(results),
            file_name="analise_cobranca_ia.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.subheader("Graficos")
    for _title, figure in figures:
        st.plotly_chart(figure, use_container_width=True)

    st.subheader("Relatorio em PDF")
    if st.button("Gerar PDF", type="primary", key="charge_ai_pdf"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORT_DIR / f"relatorio_cobranca_ia_{timestamp}.pdf"
        try:
            with st.spinner("Gerando PDF da analise de cobranca com IA..."):
                pdf_bytes = generate_charge_ai_pdf(
                    output_path=output_path,
                    period=analysis.period,
                    summary_df=formatted_summary,
                    ia_df=formatted_ia,
                    charge_df=formatted_charge,
                    status_df=formatted_status,
                    type_df=formatted_type,
                    recurrence_df=formatted_recurrence,
                    classification_df=formatted_classification,
                    daily_df=formatted_daily,
                    figures=figures,
                    conclusion=conclusion,
                )
            st.session_state["charge_ai_pdf_bytes"] = pdf_bytes
            st.session_state["charge_ai_pdf_name"] = output_path.name
            st.success(f"PDF gerado e salvo localmente em: {output_path}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Nao foi possivel gerar o PDF: {exc}")

    if st.session_state.get("charge_ai_pdf_bytes"):
        st.download_button(
            "Baixar PDF",
            data=st.session_state["charge_ai_pdf_bytes"],
            file_name=st.session_state.get("charge_ai_pdf_name", "relatorio_cobranca_ia.pdf"),
            mime="application/pdf",
            key="charge_ai_pdf_download",
        )


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


def _render_os_pro_list(title: str, items: list[dict], empty_message: str, field: str) -> None:
    st.markdown(f"**{title}**")
    if not items:
        st.caption(empty_message)
        return
    for item in items:
        st.markdown(f"- {item.get('criterio', 'Criterio')}")
        detail = item.get(field)
        if detail:
            st.caption(detail)


def _criteria_preview_dataframe(criteria: list[dict]) -> pd.DataFrame:
    rows = []
    for item in criteria:
        rows.append(
            {
                "Criterio": item.get("nome", ""),
                "Tipo": item.get("tipo", ""),
                "Peso": item.get("peso", ""),
                "Termos buscados": ", ".join(str(term) for term in item.get("termos", [])),
            }
        )
    return pd.DataFrame(rows)


def _render_os_pro_result(result: dict, ai_analysis: str | None = None) -> None:
    score = result.get("nota", 0)
    status = result.get("status", "Nao analisado")
    metric_cols = st.columns(2)
    metric_cols[0].metric("Nota final", f"{score}/100")
    metric_cols[1].metric("Status", status)

    st.progress(min(max(int(score), 0), 100) / 100)
    _render_os_pro_list(
        "Conforme",
        result.get("conformidades", []),
        "Nenhuma conformidade encontrada.",
        "evidencia",
    )
    _render_os_pro_list(
        "Nao conforme",
        result.get("nao_conformidades", []),
        "Nenhuma nao conformidade encontrada.",
        "problema",
    )

    suggestions = [item for item in result.get("nao_conformidades", []) if item.get("sugestao")]
    st.markdown("**Sugestao**")
    if suggestions:
        for item in suggestions:
            st.info(item["sugestao"])
    else:
        st.caption("Nenhuma sugestao pendente pelos criterios cadastrados.")

    tables = result_to_tables(result)
    tab_evidence, tab_nonconformity, tab_export = st.tabs(["Evidencias", "Trechos problematicos", "Exportar"])
    with tab_evidence:
        if tables["evidencias"].empty:
            st.caption("Nenhuma evidencia textual encontrada.")
        else:
            st.dataframe(tables["evidencias"], use_container_width=True, hide_index=True)
    with tab_nonconformity:
        if tables["nao_conformidades"].empty:
            st.caption("Nenhum trecho problematico encontrado.")
        else:
            st.dataframe(tables["nao_conformidades"], use_container_width=True, hide_index=True)
    with tab_export:
        export_payload = {
            "nota": result.get("nota"),
            "status": result.get("status"),
            "conformidades": result.get("conformidades", []),
            "nao_conformidades": result.get("nao_conformidades", []),
            "evidencias": result.get("evidencias", []),
        }
        st.download_button(
            "Baixar resultado JSON",
            data=json.dumps(export_payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="auditoria_os_pro.json",
            mime="application/json",
        )

    if ai_analysis:
        st.subheader("Analise avancada por IA")
        st.write(ai_analysis)


def _render_os_pro_audit() -> None:
    st.title("Auditoria OS PRO de Atendimento")
    st.caption("Analise por regras com modo IA opcional para leitura de contexto, risco e melhoria da resposta.")

    with st.sidebar:
        st.header("Modo IA opcional")
        enable_ai = st.checkbox("Ativar IA quando houver chave API", value=False)
        api_key = st.text_input("Chave API", type="password", help="A chave fica apenas nesta sessao do Streamlit.")
        model = st.text_input(
            "Modelo",
            value="auto",
            help="Use auto para tentar detectar um modelo disponivel na sua chave, ou informe um modelo especifico.",
        )
        if st.button("Testar chave API", use_container_width=True):
            diagnostic = diagnose_openai_key(api_key)
            if diagnostic["ok"]:
                st.success(diagnostic["message"])
                suggested_models = diagnostic.get("models", [])
                if suggested_models:
                    st.caption(f"Sugestao para o campo Modelo: {suggested_models[0]}")
            else:
                st.error(diagnostic["message"])
                all_models = diagnostic.get("all_models", [])
                if all_models:
                    st.caption(f"Modelos visiveis: {', '.join(all_models[:20])}")

    left, right = st.columns([1, 1])
    with left:
        st.subheader("Entrada")
        uploaded_file = st.file_uploader("Upload PDF/TXT", type=["pdf", "txt"], key="os_pro_upload")
        pasted_text = st.text_area("Cole o atendimento aqui", height=260, key="os_pro_text")
        side_text = st.text_area("Campo lateral / observacoes do atendimento", height=150, key="os_pro_side_text")

        with st.expander("Cadastre de criterios OS PRO", expanded=False):
            criteria_files = st.file_uploader(
                "PDF/TXT de criterios OS PRO (prioritario)",
                type=["pdf", "txt"],
                key="os_pro_criteria_file",
                accept_multiple_files=True,
                help="Envie de 1 a 10 arquivos em PDF ou TXT. Se enviado, este conjunto sera usado antes do JSON abaixo.",
            )
            criteria_json = st.text_area(
                "Criterios em JSON",
                value=st.session_state.get("os_pro_criteria_json", DEFAULT_CRITERIA_JSON),
                height=360,
                key="os_pro_criteria_json",
            )
            st.caption("Prioridade: PDFs/TXTs de criterios > JSON. Limite: minimo 1 e maximo 10 arquivos PRO.")

        analyze_button = st.button("Analisar Atendimento", type="primary", use_container_width=True)

    if analyze_button:
        try:
            uploaded_text = read_uploaded_text(uploaded_file)
            full_text = "\n\n".join(part.strip() for part in [uploaded_text, pasted_text, side_text] if part and part.strip())
            if not full_text:
                st.warning("Envie um PDF/TXT ou cole o atendimento para analisar.")
                st.stop()

            if criteria_files:
                if len(criteria_files) > 10:
                    st.error("Envie no maximo 10 arquivos de criterios OS PRO.")
                    st.stop()
                criteria = []
                criteria_sources = []
                criteria_failures = []
                for criteria_file in criteria_files:
                    try:
                        criteria_text = read_uploaded_text(criteria_file)
                        file_criteria = parse_criteria_document(criteria_text)
                        criteria.extend(file_criteria)
                        criteria_sources.append(f"{criteria_file.name}: {len(file_criteria)}")
                    except Exception as exc:  # noqa: BLE001 - keep processing other criteria files.
                        criteria_failures.append(f"{criteria_file.name}: {exc}")
                if criteria_failures:
                    st.warning(
                        "Alguns arquivos PRO nao tiveram criterios legiveis. "
                        "Se forem PDFs escaneados/imagem, salve com OCR ou envie em TXT. "
                        f"Arquivos: {'; '.join(criteria_failures)}"
                    )
                if not criteria:
                    st.error(
                        "Nenhum criterio foi extraido dos arquivos PRO enviados. "
                        "O PDF precisa ter texto selecionavel/OCR, ou envie os criterios em TXT/JSON."
                    )
                    st.stop()
                st.info(
                    "Criterios carregados dos arquivos PRO: "
                    f"{'; '.join(criteria_sources)}. Total: {len(criteria)} criterios."
                )
            else:
                criteria = parse_criteria_json(criteria_json)
            with st.expander("Previa dos criterios usados nesta analise", expanded=False):
                st.dataframe(_criteria_preview_dataframe(criteria), use_container_width=True, hide_index=True)
            result = analyze_os_pro(full_text, criteria)
            ai_analysis = ""
            if enable_ai and api_key.strip():
                with st.spinner("Rodando analise avancada por IA..."):
                    ai_analysis = analyze_with_ai(api_key, model, full_text, result)
            elif enable_ai:
                st.info("Modo IA marcado, mas nenhuma chave API foi informada. Rodei apenas a analise por regras.")

            st.session_state["os_pro_result"] = result
            st.session_state["os_pro_ai_analysis"] = ai_analysis
        except Exception as exc:  # noqa: BLE001 - Streamlit should show a friendly diagnostic.
            st.error(f"Nao foi possivel analisar o atendimento: {exc}")

    with right:
        st.subheader("Resultado da Auditoria")
        if st.session_state.get("os_pro_result"):
            _render_os_pro_result(
                st.session_state["os_pro_result"],
                st.session_state.get("os_pro_ai_analysis"),
            )
        else:
            st.info("O resultado aparecera aqui depois de clicar em Analisar Atendimento.")


def _auto_service_excel_bytes(results) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([results.summary]).to_excel(writer, sheet_name="Resumo", index=False)
        results.service_df.to_excel(writer, sheet_name="Servico", index=False)
        results.type_df.to_excel(writer, sheet_name="Tipo", index=False)
        results.channel_df.to_excel(writer, sheet_name="Canal", index=False)
        results.department_df.to_excel(writer, sheet_name="Departamento", index=False)
        results.prepared_data.to_excel(writer, sheet_name="Base preparada", index=False)
    return output.getvalue()


def _auto_service_month_label(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _auto_service_month_options(df: pd.DataFrame, month_col: str | None) -> list[str]:
    if not month_col or month_col not in df.columns:
        return []
    labels = [_auto_service_month_label(value) for value in df[month_col].dropna()]
    labels = sorted(
        {label for label in labels if label},
        key=lambda label: (0, int(label)) if label.isdigit() else (1, label),
    )
    return labels


def _auto_service_summary_pdf_df(summary: dict, period_label: str = "Arquivo inteiro") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Indicador": "Periodo analisado", "Resultado": period_label},
            {"Indicador": "Total de registros analisados", "Resultado": f"{format_number(summary['Registros'])} linhas"},
            {"Indicador": "Total de atendimentos/acionamentos", "Resultado": format_number(summary["Atendimentos"])},
            {"Indicador": "OS geradas", "Resultado": format_number(summary["OS geradas"])},
            {"Indicador": "OS executadas", "Resultado": format_number(summary["OS executadas"])},
            {"Indicador": "Taxa de execucao de OS", "Resultado": format_percent(summary["% OS executadas"])},
            {"Indicador": "Faturas geradas", "Resultado": format_number(summary["Faturas geradas"])},
            {"Indicador": "Faturas pagas", "Resultado": format_number(summary["Faturas pagas"])},
            {"Indicador": "Taxa de faturas pagas", "Resultado": format_percent(summary["% Faturas pagas"])},
            {"Indicador": "Boletos isentos", "Resultado": format_number(summary["Boletos isentos"])},
            {"Indicador": "Valor total das faturas", "Resultado": format_money(summary["Valor total"])},
            {"Indicador": "Valor pago estimado", "Resultado": format_money(summary["Valor pago estimado"])},
            {"Indicador": "Avaliacoes CSAT", "Resultado": format_number(summary["Avaliacoes CSAT"])},
            {"Indicador": "CSAT 4 ou 5", "Resultado": format_percent(summary["% CSAT positivo"])},
            {"Indicador": "CSAT menor ou igual a 3", "Resultado": format_percent(summary["% CSAT negativo"])},
        ]
    )


def _auto_service_bar_chart(table: pd.DataFrame, label_col: str, value_col: str, title: str) -> None:
    if table.empty or label_col not in table.columns or value_col not in table.columns:
        st.info("Nao ha dados suficientes para montar este grafico.")
        return
    chart_df = table[[label_col, value_col]].copy().head(15)
    chart_df[label_col] = chart_df[label_col].astype(str)
    chart_df = chart_df.set_index(label_col)
    st.caption(title)
    st.bar_chart(chart_df)


def _render_auto_service_table(title: str, table: pd.DataFrame) -> None:
    st.caption(title)
    if table.empty:
        st.info("Nao ha dados suficientes para montar esta tabela.")
        return
    st.dataframe(format_auto_service_table(table), use_container_width=True, hide_index=True)


def _render_auto_service_analysis() -> None:
    st.title("ANALISE DE AUTO SERVIÇO")
    st.caption("Mudanca de endereco + mudanca de comodo | OS, faturas, CSAT, canais e departamentos")

    uploaded_file = st.file_uploader(
        "CSV ou XLSX da analise de autosservico",
        type=["csv", "xlsx", "xls"],
        key="upload_autosservico",
    )
    uploaded_df = None
    month_col = None
    selected_months: list[str] = []
    if uploaded_file is not None:
        try:
            uploaded_df = read_auto_service_file(uploaded_file)
            detected_columns = detect_auto_service_columns(uploaded_df)
            month_col = detected_columns.get("mes")
            month_options = _auto_service_month_options(uploaded_df, month_col)
            if month_options:
                selected_months = st.multiselect(
                    "Meses para analisar",
                    options=month_options,
                    default=month_options,
                    help="Selecione um unico mes para analisar mes a mes, ou mantenha varios meses para uma visao consolidada.",
                )
                st.caption(f"Coluna de mes detectada: {month_col}")
            else:
                st.warning("Nao encontrei uma coluna de mes. A analise sera feita com o arquivo inteiro.")
        except Exception as exc:  # noqa: BLE001 - keep the UI actionable.
            st.error(f"Nao foi possivel ler o arquivo para montar o filtro de mes: {exc}")
            uploaded_df = None
    analyze_clicked = st.button("Analisar", type="primary", use_container_width=True)

    if analyze_clicked:
        st.session_state.pop("auto_service_pdf_bytes", None)
        st.session_state.pop("auto_service_pdf_name", None)
        if uploaded_file is None:
            st.warning("Envie um arquivo CSV ou XLSX para iniciar a analise.")
            st.stop()
        try:
            with st.spinner("Lendo arquivo e montando a analise de autosservico..."):
                df = uploaded_df if uploaded_df is not None else read_auto_service_file(uploaded_file)
                if df.empty:
                    st.warning("O arquivo enviado esta vazio.")
                    st.stop()
                if month_col and selected_months:
                    month_labels = df[month_col].apply(_auto_service_month_label)
                    df = df[month_labels.isin(selected_months)].copy()
                    if df.empty:
                        st.warning("Nenhuma linha encontrada para os meses selecionados.")
                        st.stop()
                elif month_col and not selected_months:
                    st.warning("Selecione pelo menos um mes para analisar.")
                    st.stop()
                st.session_state["auto_service_results"] = analyze_auto_service(df)
                st.session_state["auto_service_month_filter"] = ", ".join(selected_months) if selected_months else "Arquivo inteiro"
        except Exception as exc:  # noqa: BLE001 - keep the UI actionable.
            st.error(f"Nao foi possivel analisar o arquivo: {exc}")
            st.stop()

    results = st.session_state.get("auto_service_results")
    if not results:
        st.info("Envie um CSV ou XLSX e clique em Analisar para gerar a leitura de autosservico.")
        return

    summary = results.summary
    st.subheader("Resumo geral")
    st.caption(f"Periodo analisado: {st.session_state.get('auto_service_month_filter', 'Arquivo inteiro')}")
    metrics = [
        ("Registros", format_number(summary["Registros"])),
        ("Atendimentos", format_number(summary["Atendimentos"])),
        ("OS geradas", format_number(summary["OS geradas"])),
        ("OS executadas", format_number(summary["OS executadas"])),
        ("Taxa execucao OS", format_percent(summary["% OS executadas"])),
        ("Faturas geradas", format_number(summary["Faturas geradas"])),
        ("Faturas pagas", format_number(summary["Faturas pagas"])),
        ("Taxa pagamento", format_percent(summary["% Faturas pagas"])),
        ("Boletos isentos", format_number(summary["Boletos isentos"])),
        ("Valor total", format_money(summary["Valor total"])),
        ("Valor pago estimado", format_money(summary["Valor pago estimado"])),
        ("CSAT positivo", format_percent(summary["% CSAT positivo"])),
        ("CSAT negativo", format_percent(summary["% CSAT negativo"])),
    ]
    for start in range(0, len(metrics), 4):
        cols = st.columns(4)
        for col, (label, value) in zip(cols, metrics[start : start + 4]):
            col.metric(label, value)
    st.caption(
        "Valor pago estimado = ticket medio da linha (Valor total das faturas / Faturas geradas) "
        "x Faturas pagas. A base nao possui o valor individual de cada fatura paga."
    )

    st.subheader("Diagnostico principal")
    for item in results.diagnostic:
        st.write(f"- {item}")

    tab_summary, tab_ops, tab_channels, tab_issues, tab_downloads = st.tabs(
        ["Servicos", "Operacao", "Canais", "Gargalos", "Downloads"]
    )
    with tab_summary:
        st.subheader("Mudanca de endereco x mudanca de comodo")
        _render_auto_service_table("Resumo por servico", results.service_df)
        _auto_service_bar_chart(results.service_df, "__servico", "Atendimentos", "Volume por servico")
        if not results.service_df.empty:
            top_service = results.service_df.iloc[0]
            worst_execution = results.service_df.sort_values("% OS executadas", ascending=True).iloc[0]
            st.markdown("#### Leitura direta")
            st.write(f"- O servico com maior volume e **{top_service['__servico']}**, com **{format_number(top_service['Atendimentos'])} atendimentos**.")
            st.write(f"- O pior servico em execucao de OS e **{worst_execution['__servico']}**, com **{format_percent(worst_execution['% OS executadas'])}**.")

    with tab_ops:
        st.subheader("Autosservico x atendimento humano")
        _render_auto_service_table("Resumo por tipo de atendimento", results.type_df)
        _auto_service_bar_chart(results.type_df, "__tipo", "Atendimentos", "Volume por tipo de atendimento")
        if not results.type_df.empty and len(results.type_df) > 1:
            best_execution = results.type_df.sort_values("% OS executadas", ascending=False).iloc[0]
            worst_payment = results.type_df.sort_values("% Faturas pagas", ascending=True).iloc[0]
            st.write(f"- Melhor execucao de OS: **{best_execution['__tipo']}** com **{format_percent(best_execution['% OS executadas'])}**.")
            st.write(f"- Pior pagamento de faturas: **{worst_payment['__tipo']}** com **{format_percent(worst_payment['% Faturas pagas'])}**.")

    with tab_channels:
        st.subheader("App Minha Valenet x WhatsApp")
        _render_auto_service_table("Resumo por canal/integracao", results.channel_df)
        _auto_service_bar_chart(results.channel_df, "__canal", "Atendimentos", "Volume por canal")
        channels_without_csat = results.channel_df[(results.channel_df["Atendimentos"] > 0) & (results.channel_df["Avaliacoes_CSAT"] == 0)]
        for _, row in channels_without_csat.iterrows():
            st.error(
                f"O canal **{row['__canal']}** possui **{format_number(row['Atendimentos'])} atendimentos** "
                "e zero avaliacao CSAT. Isso e ponto cego de satisfacao."
            )

        st.subheader("Analise por departamento/equipe")
        _render_auto_service_table("Resumo por departamento/equipe", results.department_df)
        _auto_service_bar_chart(results.department_df, "__departamento", "Atendimentos", "Volume por departamento/equipe")
        if not results.department_df.empty:
            top_department = results.department_df.iloc[0]
            worst_department_execution = results.department_df.sort_values("% OS executadas", ascending=True).iloc[0]
            worst_department_payment = results.department_df.sort_values("% Faturas pagas", ascending=True).iloc[0]
            st.write(f"- Maior volume: **{top_department['__departamento']}**, com **{format_number(top_department['Atendimentos'])} atendimentos**.")
            st.write(f"- Pior execucao de OS: **{worst_department_execution['__departamento']}**, com **{format_percent(worst_department_execution['% OS executadas'])}**.")
            st.write(f"- Pior pagamento: **{worst_department_payment['__departamento']}**, com **{format_percent(worst_department_payment['% Faturas pagas'])}**.")

    with tab_issues:
        st.subheader("Principais gargalos")
        for item in results.bottlenecks:
            st.write(f"- {item}")

        st.subheader("Pontos estranhos da base")
        for item in results.odd_points:
            st.write(f"- {item}")

        with st.expander("Ver linhas com OS maior que atendimentos"):
            st.dataframe(results.odd_os_rows, use_container_width=True, hide_index=True)
        with st.expander("Ver linhas com fatura gerada e sem pagamento"):
            st.dataframe(results.odd_invoice_rows, use_container_width=True, hide_index=True)

        st.subheader("Conclusao")
        if summary["% OS executadas"] < 60 or summary["% Faturas pagas"] < 30:
            st.warning(results.conclusion)
        else:
            st.success(results.conclusion)

        st.subheader("Acoes recomendadas")
        for item in results.recommendations:
            st.write(f"- {item}")

    with tab_downloads:
        st.download_button(
            "Baixar Excel da analise",
            data=_auto_service_excel_bytes(results),
            file_name="analise_auto_servico.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        with st.expander("Colunas identificadas automaticamente"):
            st.json(results.detected_columns)
        with st.expander("Base carregada"):
            st.dataframe(results.original_data, use_container_width=True, hide_index=True)

    st.subheader("Relatorio em PDF")
    if st.button("Gerar PDF completo", type="primary", key="auto_service_pdf"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORT_DIR / f"relatorio_auto_servico_{timestamp}.pdf"
        try:
            with st.spinner("Gerando PDF completo com logo Valenet..."):
                pdf_bytes = generate_auto_service_pdf(
                    output_path=output_path,
                    summary_df=_auto_service_summary_pdf_df(summary, st.session_state.get("auto_service_month_filter", "Arquivo inteiro")),
                    service_df=format_auto_service_table(results.service_df),
                    type_df=format_auto_service_table(results.type_df),
                    channel_df=format_auto_service_table(results.channel_df),
                    department_df=format_auto_service_table(results.department_df),
                    diagnostic=results.diagnostic,
                    bottlenecks=results.bottlenecks,
                    odd_points=results.odd_points,
                    conclusion=results.conclusion,
                    recommendations=results.recommendations,
                )
            st.session_state["auto_service_pdf_bytes"] = pdf_bytes
            st.session_state["auto_service_pdf_name"] = output_path.name
            st.success(f"PDF gerado e salvo localmente em: {output_path}")
        except Exception as exc:  # noqa: BLE001 - keep UI friendly.
            st.error(f"Nao foi possivel gerar o PDF: {exc}")
    if st.session_state.get("auto_service_pdf_bytes"):
        st.download_button(
            "Baixar PDF",
            data=st.session_state["auto_service_pdf_bytes"],
            file_name=st.session_state.get("auto_service_pdf_name", "relatorio_auto_servico.pdf"),
            mime="application/pdf",
            key="auto_service_pdf_download",
        )


st.sidebar.header("Regras da analise")
filter_label = st.sidebar.radio(
    "Recorte analisado",
    [
        "Auditoria OS PRO",
        "ANALISE DE AUTO SERVIÇO",
        "Arquivo inteiro",
        "Busca personalizada",
        "Cobranca com IA",
        "Cobranca HSM D44",
    ],
)
filter_mode = {
    "Auditoria OS PRO": "os_pro",
    "ANALISE DE AUTO SERVIÇO": "autoservice",
    "Arquivo inteiro": FILTER_ALL,
    "Busca personalizada": FILTER_CUSTOM,
    "Cobranca com IA": "charge_ai",
    "Cobranca HSM D44": "d44",
}[filter_label]

if filter_mode == "os_pro":
    _render_os_pro_audit()
    st.stop()
if filter_mode == "autoservice":
    _render_auto_service_analysis()
    st.stop()

st.title("Analise comparativa de relatorios CSV de atendimento")
st.caption("Mudanca de Endereco + Mudanca de Comodo | TMA, TME, status, classificacao e contagem de taxa")

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
    st.subheader("Arquivo principal" if filter_mode in {"charge_ai", "d44"} else "Mes 1")
    default_name = "Cobranca IA" if filter_mode == "charge_ai" else "Cobranca HSM D44" if filter_mode == "d44" else "Maio"
    month_1 = st.text_input("Nome da analise" if filter_mode in {"charge_ai", "d44"} else "Nome do mes 1", value=default_name)
    upload_label = "CSV da cobranca com IA" if filter_mode == "charge_ai" else "CSV da Cobranca HSM D44" if filter_mode == "d44" else "CSV do mes 1"
    upload_1 = st.file_uploader(upload_label, type=["csv"], key="upload_1")
with right:
    if filter_mode == "charge_ai":
        st.subheader("Modo Cobranca com IA")
        st.info("Este modo usa o CSV completo enviado no arquivo principal. O segundo arquivo nao e necessario.")
        month_2 = "Comparativo"
        upload_2 = None
    elif filter_mode == "d44":
        st.subheader("Comparativo opcional")
        st.info("Envie um segundo CSV se quiser comparar dois periodos D44. Com um CSV, o app analisa apenas o arquivo principal.")
        month_2 = st.text_input("Nome do periodo 2", value="Comparativo D44")
        upload_2 = st.file_uploader("CSV D44 do periodo 2 (opcional)", type=["csv"], key="upload_2")
    else:
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
        detector_1 = detect_charge_ai_columns if filter_mode == "charge_ai" else detect_d44_columns if filter_mode == "d44" else detect_columns
        controls_1 = _column_controls(result_1.dataframe, detector_1(result_1.dataframe), "m1")
    with col_map_2:
        st.markdown(f"**{month_2}**")
        detector_2 = detect_charge_ai_columns if filter_mode == "charge_ai" else detect_d44_columns if filter_mode == "d44" else detect_columns
        controls_2 = _column_controls(result_2.dataframe, detector_2(result_2.dataframe), "m2")
elif filter_mode in {"charge_ai", "d44"} and result_1:
    st.subheader("Mapeamento de colunas")
    detector = detect_charge_ai_columns if filter_mode == "charge_ai" else detect_d44_columns
    controls_1 = _column_controls(result_1.dataframe, detector(result_1.dataframe), "m1")

analyze_clicked = st.button("Analisar", type="primary", use_container_width=True)

if analyze_clicked:
    st.session_state.pop("pdf_bytes", None)
    st.session_state.pop("charge_ai_pdf_bytes", None)
    st.session_state.pop("d44_pdf_bytes", None)
    try:
        if filter_mode == "charge_ai":
            if not upload_1:
                st.warning("Envie pelo menos o CSV do Mes 1 para iniciar a analise de Cobranca com IA.")
                st.stop()
            if not result_1:
                st.error("Corrija os erros de leitura do arquivo antes de analisar.")
                st.stop()
            if not controls_1:
                st.error("Confira o mapeamento das colunas antes de analisar.")
                st.stop()
            if not controls_1["attendance_time_col"]:
                st.error("Selecione a coluna de tempo de atendimento (TMA).")
                st.stop()

            charge_detected = detect_charge_ai_columns(result_1.dataframe)
            analysis = analyze_charge_ai(
                result_1.dataframe,
                month_1,
                attendance_time_col=controls_1["attendance_time_col"],
                wait_time_col=controls_1["wait_time_col"],
                status_col=controls_1["status_col"],
                text_columns=controls_1["text_columns"],
                type_col=controls_1["type_col"],
                classification_col=controls_1["classification_col"],
                recurrence_col=charge_detected.get("recurrence"),
                date_col=controls_1["date_col"],
            )
            summary_df = pd.DataFrame([analysis.summary_row])
            status_df = pd.DataFrame(analysis.status_rows)
            type_df = pd.DataFrame(analysis.type_rows)
            classification_df = pd.DataFrame(analysis.classification_rows)
            ia_df = pd.DataFrame(analysis.ia_rows)
            charge_df = pd.DataFrame(analysis.charge_rows)
            recurrence_df = pd.DataFrame(analysis.recurrence_rows)
            daily_df = pd.DataFrame(analysis.daily_rows)
            figures = create_charge_ai_figures(status_df, type_df, ia_df, charge_df, classification_df, daily_df)
            st.session_state["charge_ai_results"] = {
                "analysis": analysis,
                "summary_df": summary_df,
                "status_df": status_df,
                "type_df": type_df,
                "classification_df": classification_df,
                "ia_df": ia_df,
                "charge_df": charge_df,
                "recurrence_df": recurrence_df,
                "daily_df": daily_df,
                "formatted_summary": format_charge_summary(summary_df),
                "formatted_status": format_metric_table(status_df),
                "formatted_type": format_metric_table(type_df),
                "formatted_classification": format_metric_table(classification_df),
                "formatted_ia": format_tag_table(ia_df),
                "formatted_charge": format_tag_table(charge_df),
                "formatted_recurrence": format_tag_table(recurrence_df),
                "formatted_daily": format_metric_table(daily_df),
                "figures": figures,
                "conclusion": analysis.conclusion,
            }
            st.session_state.pop("analysis_results", None)
            _render_charge_ai_analysis(st.session_state["charge_ai_results"])
            st.stop()

        if filter_mode == "d44":
            if not upload_1:
                st.warning("Envie pelo menos o CSV principal para iniciar a analise de Cobranca HSM D44.")
                st.stop()
            if not result_1 or (upload_2 and not result_2):
                st.error("Corrija os erros de leitura dos arquivos antes de analisar.")
                st.stop()
            if not controls_1 or (result_2 and not controls_2):
                st.error("Confira o mapeamento das colunas antes de analisar.")
                st.stop()
            if not controls_1["attendance_time_col"] or (controls_2 and not controls_2["attendance_time_col"]):
                st.error("Selecione a coluna de tempo de atendimento (TMA).")
                st.stop()

            detected_1 = detect_d44_columns(result_1.dataframe)
            analysis_1 = analyze_d44(
                result_1.dataframe,
                month_1,
                attendance_time_col=controls_1["attendance_time_col"],
                wait_time_col=controls_1["wait_time_col"],
                status_col=controls_1["status_col"],
                text_columns=controls_1["text_columns"],
                type_col=controls_1["type_col"],
                classification_col=controls_1["classification_col"],
                date_col=controls_1["date_col"],
                pending_time_col=detected_1.get("pending_time"),
            )
            analyses = [analysis_1]
            if result_2 and controls_2:
                detected_2 = detect_d44_columns(result_2.dataframe)
                analyses.append(
                    analyze_d44(
                        result_2.dataframe,
                        month_2,
                        attendance_time_col=controls_2["attendance_time_col"],
                        wait_time_col=controls_2["wait_time_col"],
                        status_col=controls_2["status_col"],
                        text_columns=controls_2["text_columns"],
                        type_col=controls_2["type_col"],
                        classification_col=controls_2["classification_col"],
                        date_col=controls_2["date_col"],
                        pending_time_col=detected_2.get("pending_time"),
                    )
                )

            summary_df = pd.DataFrame([analysis.summary_row for analysis in analyses])
            comparison_df = build_d44_comparison_dataframe(analyses)
            status_df = combine_rows(analyses, "status_rows")
            type_df = combine_rows(analyses, "type_rows")
            classification_df = combine_rows(analyses, "classification_rows")
            hsm_df = combine_rows(analyses, "hsm_rows")
            proposal_df = combine_rows(analyses, "proposal_rows")
            proposal_cross_df = combine_rows(analyses, "proposal_cross_rows")
            charge_df = combine_rows(analyses, "charge_rows")
            daily_df = combine_rows(analyses, "daily_rows")
            figures = create_d44_figures(status_df, hsm_df, proposal_df, proposal_cross_df, daily_df)
            conclusion = " ".join(f"{analysis.month}: {analysis.conclusion}" for analysis in analyses)
            st.session_state["d44_results"] = {
                "analyses": analyses,
                "summary_df": summary_df,
                "comparison_df": comparison_df,
                "status_df": status_df,
                "type_df": type_df,
                "classification_df": classification_df,
                "hsm_df": hsm_df,
                "proposal_df": proposal_df,
                "proposal_cross_df": proposal_cross_df,
                "charge_df": charge_df,
                "daily_df": daily_df,
                "formatted_summary": format_d44_summary(summary_df),
                "formatted_comparison": format_d44_summary(comparison_df),
                "formatted_status": format_d44_metric_table(status_df),
                "formatted_type": format_d44_metric_table(type_df),
                "formatted_classification": format_d44_metric_table(classification_df),
                "formatted_hsm": format_d44_metric_table(hsm_df),
                "formatted_proposal": format_d44_metric_table(proposal_df),
                "formatted_proposal_cross": format_d44_metric_table(proposal_cross_df),
                "formatted_charge": format_d44_metric_table(charge_df),
                "formatted_daily": format_d44_metric_table(daily_df),
                "figures": figures,
                "conclusion": conclusion,
            }
            st.session_state.pop("analysis_results", None)
            st.session_state.pop("charge_ai_results", None)
            _render_d44_analysis(st.session_state["d44_results"])
            st.stop()

        if not upload_1 or not upload_2:
            st.warning("Envie os dois arquivos CSV para iniciar a analise.")
            st.stop()
        if not result_1 or not result_2:
            st.error("Corrija os erros de leitura dos arquivos antes de analisar.")
            st.stop()
        if not controls_1 or not controls_2:
            st.error("Confira o mapeamento das colunas antes de analisar.")
            st.stop()
        if not controls_1["attendance_time_col"] or not controls_2["attendance_time_col"]:
            st.error("Selecione a coluna de tempo de atendimento (TMA) para os dois meses.")
            st.stop()

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

if filter_mode not in {"charge_ai", "d44"} and st.session_state.get("analysis_results"):
    _render_analysis(st.session_state["analysis_results"])
if filter_mode == "charge_ai" and st.session_state.get("charge_ai_results"):
    _render_charge_ai_analysis(st.session_state["charge_ai_results"])
if filter_mode == "d44" and st.session_state.get("d44_results"):
    _render_d44_analysis(st.session_state["d44_results"])
