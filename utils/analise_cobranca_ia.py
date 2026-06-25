from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .analise_atendimento import detect_columns, find_best_column
from .tratamento_tempo import duration_to_seconds, format_seconds


IA_TAGS = (
    "Velma - Piloto IA",
    "Velma - Dados validados",
    "Velma - IA transferiu para agente",
    "Velma - Finalizado pela IA",
    "Velma - Nao respondeu IA",
    "Velma - Erro API",
    "Velma - Excedeu Tentativas IA",
)

CHARGE_TAGS = (
    "Cobranca",
    "Cobranca - 1 Nivel",
    "Retencao para Cobranca N1",
    "Dificuldade em pagar",
    "Fatura atrasada",
    "Identificar tipo de pagamento",
    "PIX",
    "Codigo de barras",
    "Autosservico 2 via PIX",
    "Autosservico 2 via baixar fatura",
    "Contestar valores",
    "Item da fatura",
    "Valor diferente",
    "Ja paguei",
    "Comprovante",
    "Baixa de pagamento",
)

RECURRENCE_GROUPS = ("Reincidente", "Recorrente", "Rechamada", "Sem marcacao")

EXTRA_COLUMN_CANDIDATES = {
    "recurrence": ("recorrencia", "reincidencia", "rechamada"),
    "tags": ("tag", "tags", "etiqueta", "marcador"),
    "service": ("servico", "serviço"),
    "subject": ("assunto", "tema"),
    "reason": ("motivo", "causa"),
}


@dataclass(frozen=True)
class ChargeAIAnalysis:
    month: str
    warnings: list[str]
    period: str
    summary_row: dict[str, Any]
    status_rows: list[dict[str, Any]]
    type_rows: list[dict[str, Any]]
    classification_rows: list[dict[str, Any]]
    ia_rows: list[dict[str, Any]]
    charge_rows: list[dict[str, Any]]
    recurrence_rows: list[dict[str, Any]]
    daily_rows: list[dict[str, Any]]
    conclusion: str
    prepared_data: pd.DataFrame


def normalize_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


def _display_value(value: Any, fallback: str) -> str:
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "-"}:
        return fallback
    return text


def detect_charge_ai_columns(df: pd.DataFrame) -> dict[str, Any]:
    detected = detect_columns(df)
    columns = [str(col) for col in df.columns]
    for key, candidates in EXTRA_COLUMN_CANDIDATES.items():
        detected[key] = find_best_column(columns, candidates)
    text_columns = set(detected.get("text_columns") or [])
    for key in ("tags", "service", "subject", "reason", "classification"):
        col = detected.get(key)
        if col:
            text_columns.add(col)
    detected["text_columns"] = [col for col in columns if col in text_columns]
    return detected


def _mean(series: pd.Series) -> float:
    return float(series.mean()) if len(series) else 0.0


def _median(series: pd.Series) -> float:
    return float(series.median()) if len(series) else 0.0


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else 0.0


def _row_text(row: pd.Series, columns: list[str]) -> str:
    return " | ".join(normalize_text(row.get(col, "")) for col in columns)


def _contains_tag(text: str, tag: str) -> bool:
    return normalize_text(tag) in normalize_text(text)


def _period_info(series: pd.Series | None) -> tuple[str, str]:
    if series is None or series.empty:
        return "Nao identificado", "Nao identificado"
    dates = pd.to_datetime(series, errors="coerce", dayfirst=True)
    dates = dates.dropna()
    if dates.empty:
        return "Nao identificado", "Nao identificado"
    return f"{dates.min():%d/%m/%Y}", f"{dates.max():%d/%m/%Y}"


def _metric_rows(df: pd.DataFrame, group_col: str, label_col: str, total: int, top_n: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, subset in df.groupby(group_col, dropna=False):
        volume = len(subset)
        inactivity = int(subset["_inatividade"].sum())
        rows.append(
            {
                label_col: _display_value(label, "Nao identificado"),
                "Volume": volume,
                "% Volume": _pct(volume, total),
                "TMA": _mean(subset["_tma_seconds"]),
                "Mediana TMA": _median(subset["_tma_seconds"]),
                "TME": _mean(subset["_tme_seconds"]),
                "Inatividade": inactivity,
                "% Inatividade": _pct(inactivity, volume),
            }
        )
    rows.sort(key=lambda item: (item["Inatividade"], item["Volume"], item["TMA"]), reverse=True)
    return rows[:top_n] if top_n else rows


def _tag_rows(df: pd.DataFrame, tags: tuple[str, ...], label_col: str) -> list[dict[str, Any]]:
    total = len(df)
    rows = []
    for tag in tags:
        count = int(df["_texto_analise"].apply(lambda text: _contains_tag(text, tag)).sum()) if total else 0
        rows.append({label_col: tag, "Volume": count, "% Volume": _pct(count, total)})
    rows.sort(key=lambda item: item["Volume"], reverse=True)
    return rows


def _recurrence_rows(df: pd.DataFrame, recurrence_col: str | None) -> list[dict[str, Any]]:
    total = len(df)
    source = df[recurrence_col].apply(normalize_text) if recurrence_col and recurrence_col in df.columns else pd.Series("", index=df.index)
    rows = []
    matched = pd.Series(False, index=df.index)
    for label in RECURRENCE_GROUPS[:-1]:
        mask = source.str.contains(normalize_text(label), regex=False)
        matched = matched | mask
        count = int(mask.sum())
        rows.append({"Recorrencia": label, "Volume": count, "% Volume": _pct(count, total)})
    count_unmarked = int((~matched).sum()) if total else 0
    rows.append({"Recorrencia": "Sem marcacao", "Volume": count_unmarked, "% Volume": _pct(count_unmarked, total)})
    return rows


def _daily_rows(df: pd.DataFrame, date_col: str | None) -> list[dict[str, Any]]:
    if not date_col or date_col not in df.columns:
        return []
    data = df.copy()
    data["_data_dia"] = pd.to_datetime(data[date_col], errors="coerce", dayfirst=True).dt.date
    data = data.dropna(subset=["_data_dia"])
    rows = []
    for day, subset in data.groupby("_data_dia"):
        volume = len(subset)
        inactivity = int(subset["_inatividade"].sum())
        rows.append(
            {
                "Data": day.strftime("%d/%m/%Y"),
                "Volume": volume,
                "TMA": _mean(subset["_tma_seconds"]),
                "Mediana TMA": _median(subset["_tma_seconds"]),
                "TME": _mean(subset["_tme_seconds"]),
                "Inatividade": inactivity,
                "% Inatividade": _pct(inactivity, volume),
            }
        )
    return rows


def _charge_ai_conclusion(summary: dict[str, Any], ia_df: pd.DataFrame, charge_df: pd.DataFrame, recurrence_df: pd.DataFrame) -> str:
    total = int(summary["Total de atendimentos"])
    messages: list[str] = []

    charge_total = int(charge_df["Volume"].sum()) if not charge_df.empty else 0
    if total and charge_total / total >= 1:
        messages.append("A cobranca e predominante nos registros analisados.")
    elif charge_total:
        messages.append("Ha presenca relevante de marcacoes de cobranca no periodo.")

    validated = _lookup_volume(ia_df, "Tag IA Velma", "Velma - Dados validados")
    transferred = _lookup_volume(ia_df, "Tag IA Velma", "Velma - IA transferiu para agente")
    finalized_ai = _lookup_volume(ia_df, "Tag IA Velma", "Velma - Finalizado pela IA")
    error_api = _lookup_volume(ia_df, "Tag IA Velma", "Velma - Erro API")
    if validated:
        messages.append(f"A IA validou dados em {validated} atendimentos.")
    if total and transferred / total >= 0.2:
        messages.append("A IA esta transferindo volume alto para agente.")
    if finalized_ai:
        messages.append(f"A IA finalizou {finalized_ai} atendimentos.")
    if error_api:
        messages.append(f"Foram identificados {error_api} casos de erro de API.")

    inactivity_pct = float(summary["% Inatividade"])
    if inactivity_pct >= 30:
        messages.append("A inatividade esta alta e pode estar inflando o TMA.")
    elif inactivity_pct >= 15:
        messages.append("A inatividade merece acompanhamento, pois pode impactar o TMA.")

    for tag in ("Dificuldade em pagar", "Fatura atrasada", "Contestar valores"):
        count = _lookup_volume(charge_df, "Tag cobranca", tag)
        if total and count / total >= 0.1:
            messages.append(f"Ha volume relevante em {tag.lower()}.")

    recurrence_count = int(recurrence_df[recurrence_df["Recorrencia"].isin(["Reincidente", "Recorrente", "Rechamada"])]["Volume"].sum()) if not recurrence_df.empty else 0
    if total and recurrence_count / total >= 0.2:
        messages.append("Recorrencia/rechamada esta alta e indica retorno frequente do cliente.")

    return " ".join(messages) if messages else "A analise de cobranca com IA foi processada sem anomalias relevantes aparentes."


def _lookup_volume(df: pd.DataFrame, label_col: str, label: str) -> int:
    if df.empty or label_col not in df.columns:
        return 0
    match = df[df[label_col].apply(normalize_text) == normalize_text(label)]
    return int(match["Volume"].sum()) if not match.empty else 0


def analyze_charge_ai(
    df: pd.DataFrame,
    month: str,
    attendance_time_col: str,
    wait_time_col: str | None,
    status_col: str | None,
    text_columns: list[str],
    type_col: str | None = None,
    classification_col: str | None = None,
    recurrence_col: str | None = None,
    date_col: str | None = None,
) -> ChargeAIAnalysis:
    warnings: list[str] = []
    if not attendance_time_col or attendance_time_col not in df.columns:
        raise ValueError("Selecione uma coluna valida de tempo de atendimento (TMA) para a analise de cobranca com IA.")

    data = df.copy()
    total = len(data)
    text_columns = [col for col in text_columns if col in data.columns]
    if not text_columns:
        text_columns = [col for col in data.columns if data[col].dtype == "object"]
        warnings.append("Campos textuais especificos nao foram identificados; usando colunas de texto disponiveis.")

    if not status_col or status_col not in data.columns:
        warnings.append("Coluna de status nao identificada. Finalizacao e inatividade podem ficar zeradas.")
    if not wait_time_col or wait_time_col not in data.columns:
        warnings.append("Coluna de TME nao identificada. TME considerado como 0.")
    if not type_col or type_col not in data.columns:
        warnings.append("Coluna de tipo de atendimento nao identificada.")
    if not classification_col or classification_col not in data.columns:
        warnings.append("Coluna de classificacao nao identificada.")
    if not recurrence_col or recurrence_col not in data.columns:
        warnings.append("Coluna de recorrencia nao identificada.")
    if not date_col or date_col not in data.columns:
        warnings.append("Coluna de data nao identificada. Periodo e analise por dia podem ficar indisponiveis.")

    data["_texto_analise"] = data.apply(lambda row: _row_text(row, text_columns), axis=1)
    data["_status_norm"] = data[status_col].apply(normalize_text) if status_col in data.columns else ""
    data["_status_label"] = data[status_col].apply(lambda value: _display_value(value, "Sem status")) if status_col in data.columns else "Sem status"
    data["_type_label"] = data[type_col].apply(lambda value: _display_value(value, "Nao identificado")) if type_col in data.columns else "Nao identificado"
    data["_classification_label"] = data[classification_col].apply(lambda value: _display_value(value, "Nao identificado")) if classification_col in data.columns else "Nao identificado"
    data["_tma_seconds"] = data[attendance_time_col].apply(duration_to_seconds)
    data["_tme_seconds"] = data[wait_time_col].apply(duration_to_seconds) if wait_time_col in data.columns else 0
    data["_finalizado_real"] = data["_status_norm"].eq("finalizado")
    data["_inatividade"] = data["_status_norm"].str.contains("inatividade", regex=False)
    data["_transferido"] = data["_status_norm"].str.contains("transfer", regex=False)

    no_inactivity = data[~data["_inatividade"]]
    start_date, end_date = _period_info(data[date_col] if date_col in data.columns else None)
    period = f"{start_date} a {end_date}" if start_date != "Nao identificado" else "Nao identificado"
    real_finished = int(data["_finalizado_real"].sum())
    inactivity = int(data["_inatividade"].sum())
    transferred = int(data["_transferido"].sum())
    type_norm = data["_type_label"].apply(normalize_text)
    ia_df = pd.DataFrame(_tag_rows(data, IA_TAGS, "Tag IA Velma"))
    charge_df = pd.DataFrame(_tag_rows(data, CHARGE_TAGS, "Tag cobranca"))
    recurrence_df = pd.DataFrame(_recurrence_rows(data, recurrence_col))

    summary_row = {
        "Mes": month,
        "Total de atendimentos": total,
        "Periodo analisado": period,
        "TMA geral": _mean(data["_tma_seconds"]),
        "Mediana TMA": _median(data["_tma_seconds"]),
        "TMA sem inatividade": _mean(no_inactivity["_tma_seconds"]),
        "Mediana sem inatividade": _median(no_inactivity["_tma_seconds"]),
        "TME geral": _mean(data["_tme_seconds"]),
        "Mediana TME": _median(data["_tme_seconds"]),
        "Finalizados reais": real_finished,
        "% Finalizacao real": _pct(real_finished, total),
        "Finalizados por inatividade": inactivity,
        "% Inatividade": _pct(inactivity, total),
        "Transferidos": transferred,
        "% Transferencia": _pct(transferred, total),
        "Atendimentos automaticos": int(type_norm.str.contains("automatico", regex=False).sum()),
        "Atendimentos mistos": int(type_norm.str.contains("misto", regex=False).sum()),
        "Atendimentos humanos": int(type_norm.str.contains("humano", regex=False).sum()),
        "IA transferiu para agente": _lookup_volume(ia_df, "Tag IA Velma", "Velma - IA transferiu para agente"),
        "Finalizado pela IA": _lookup_volume(ia_df, "Tag IA Velma", "Velma - Finalizado pela IA"),
        "Erro API": _lookup_volume(ia_df, "Tag IA Velma", "Velma - Erro API"),
    }

    status_rows = _metric_rows(data, "_status_label", "Status", total)
    type_rows = _metric_rows(data, "_type_label", "Tipo", total)
    classification_rows = _metric_rows(data, "_classification_label", "Classificacao", total, top_n=20)
    daily_rows = _daily_rows(data, date_col)
    conclusion = _charge_ai_conclusion(summary_row, ia_df, charge_df, recurrence_df)

    return ChargeAIAnalysis(
        month=month,
        warnings=warnings,
        period=period,
        summary_row=summary_row,
        status_rows=status_rows,
        type_rows=type_rows,
        classification_rows=classification_rows,
        ia_rows=ia_df.to_dict("records"),
        charge_rows=charge_df.to_dict("records"),
        recurrence_rows=recurrence_df.to_dict("records"),
        daily_rows=daily_rows,
        conclusion=conclusion,
        prepared_data=data,
    )


def format_charge_summary(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    for column in ("TMA geral", "Mediana TMA", "TMA sem inatividade", "Mediana sem inatividade", "TME geral", "Mediana TME"):
        if column in formatted.columns:
            formatted[column] = formatted[column].apply(format_seconds)
    for column in ("% Finalizacao real", "% Inatividade", "% Transferencia"):
        if column in formatted.columns:
            formatted[column] = formatted[column].map(lambda value: f"{float(value):.1f}%")
    return formatted


def format_metric_table(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    for column in ("TMA", "Mediana TMA", "TME"):
        if column in formatted.columns:
            formatted[column] = formatted[column].apply(format_seconds)
    for column in ("% Volume", "% Inatividade"):
        if column in formatted.columns:
            formatted[column] = formatted[column].map(lambda value: f"{float(value):.1f}%")
    return formatted


def format_tag_table(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    for column in ("% Volume",):
        if column in formatted.columns:
            formatted[column] = formatted[column].map(lambda value: f"{float(value):.1f}%")
    return formatted
