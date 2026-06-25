from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .tratamento_tempo import duration_to_seconds, format_seconds


LOW_VOLUME_THRESHOLD = 30
LOW_VOLUME_MESSAGE = "Atencao: este mes possui baixo volume de atendimentos e pode nao representar o periodo completo."
LOW_VOLUME_CONCLUSION = "A comparacao deve ser lida com cautela, pois um dos meses possui baixo volume de atendimentos."
UNKNOWN_FEE_GROUP = "Sem identificacao clara"
TAX_GROUPS = ("Com taxa", "Sem taxa", UNKNOWN_FEE_GROUP)

TEXT_FIELD_KEYWORDS = (
    "tag",
    "classificacao",
    "assunto",
    "servico",
    "motivo",
    "fila",
    "categoria",
)

NON_TEXT_COLUMN_KEYWORDS = (
    "data",
    "hora",
    "tempo",
    "duracao",
    "tma",
    "tme",
    "tmic",
    "tmia",
    "qic",
    "qia",
)

CHANGE_TERMS = (
    "mudanca de endereco",
    "mudanca endereco",
    "mudanca de comodo",
    "mudanca comodo",
)

WITHOUT_FEE_PATTERNS = (
    r"\bsem\s+(?:taxa|cobranca|custo)\b",
    r"\bs[/ ]?taxa\b",
    r"\bisent[oa]\b",
    r"\bisencao\b",
    r"\btaxa\s+isenta\b",
    r"\bnao\s+(?:tem|possui|cobra)\s+taxa\b",
    r"\btaxa\s+(?:zero|0)\b",
)

WITH_FEE_PATTERNS = (
    r"\bcom\s+(?:taxa|cobranca)\b",
    r"\bc[/ ]?taxa\b",
    r"\btaxa\s+(?:de\s+)?mudanca\b",
    r"\bcobranca\s+de\s+taxa\b",
    r"\btaxa\s+(?:aceita|aprovada|cobrada|aplicada)\b",
)

COLUMN_CANDIDATES = {
    "status": ("status", "situacao", "estado", "resultado"),
    "attendance_time": (
        "tempo atendimento",
        "duracao atendimento",
        "duracao do atendimento",
        "tempo de atendimento",
        "tma",
        "tempo conversa",
        "tempo total atendimento",
    ),
    "wait_time": (
        "tempo espera",
        "tempo de espera",
        "tempo fila",
        "tempo em fila",
        "espera",
        "fila espera",
        "tme",
    ),
    "date": (
        "data de entrada",
        "data entrada",
        "data criacao",
        "data de criacao",
        "data abertura",
        "abertura",
        "criado em",
    ),
    "type": ("tipo", "tipo atendimento", "modalidade", "canal atendimento"),
    "classification": ("classificacao", "classificacao atendimento", "categoria", "motivo"),
}


@dataclass(frozen=True)
class MonthAnalysis:
    month: str
    period: str
    period_start: str
    period_end: str
    period_days: int
    total_file: int
    total_change: int
    total_with_fee: int
    total_without_fee: int
    total_unknown_fee: int
    general_inactivity: int
    general_inactivity_pct: float
    general_tma_seconds: float
    general_tme_seconds: float
    median_tma_seconds: float
    tma_without_inactivity_seconds: float
    median_without_inactivity_seconds: float
    max_tma_seconds: float
    comparison_row: dict[str, Any]
    period_row: dict[str, Any]
    fee_rows: list[dict[str, Any]]
    status_rows: list[dict[str, Any]]
    type_rows: list[dict[str, Any]]
    classification_rows: list[dict[str, Any]]
    filtered_data: pd.DataFrame


def normalize_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_column_name(value: Any) -> str:
    text = normalize_text(value)
    text = re.sub(r"[_\-/]+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _score_column(normalized_column: str, candidate: str) -> int:
    candidate_norm = normalize_column_name(candidate)
    tokens = [token for token in candidate_norm.split() if token]
    if not tokens:
        return 0
    if candidate_norm == normalized_column:
        return 100 + len(candidate_norm)
    if candidate_norm in normalized_column:
        return 80 + len(candidate_norm)
    if all(token in normalized_column for token in tokens):
        return 50 + len(tokens)
    return 0


def find_best_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    best: tuple[int, str | None] = (0, None)
    for column in columns:
        normalized = normalize_column_name(column)
        score = max(_score_column(normalized, candidate) for candidate in candidates)
        if score > best[0]:
            best = (score, column)
    return best[1]


def detect_columns(df: pd.DataFrame) -> dict[str, Any]:
    columns = [str(col) for col in df.columns]
    detected = {
        semantic: find_best_column(columns, candidates)
        for semantic, candidates in COLUMN_CANDIDATES.items()
    }
    text_columns = []
    for col in columns:
        normalized = normalize_column_name(col)
        is_text_candidate = any(keyword in normalized for keyword in TEXT_FIELD_KEYWORDS)
        is_metric_or_date = any(keyword in normalized for keyword in NON_TEXT_COLUMN_KEYWORDS)
        if is_text_candidate and not is_metric_or_date:
            text_columns.append(col)
    detected["text_columns"] = text_columns
    return detected


def textual_columns_warning(text_columns: list[str]) -> str | None:
    if len(text_columns) < 2:
        return (
            "Poucos campos textuais relevantes foram identificados. "
            "Confira a selecao manual para melhorar o filtro do recorte."
        )
    return None


def _row_text(row: pd.Series, columns: list[str]) -> str:
    values = [normalize_text(row.get(column, "")) for column in columns]
    return " | ".join(value for value in values if value)


def classify_fee(text: str) -> str:
    normalized = normalize_text(text)
    if any(re.search(pattern, normalized) for pattern in WITHOUT_FEE_PATTERNS):
        return "Sem taxa"
    if any(re.search(pattern, normalized) for pattern in WITH_FEE_PATTERNS):
        return "Com taxa"
    if _has_generic_fee_context(normalized):
        return "Com taxa"
    return UNKNOWN_FEE_GROUP


def _has_generic_fee_context(text: str) -> bool:
    if "taxa" not in text:
        return False
    fee_index = text.find("taxa")
    window = text[max(0, fee_index - 60) : fee_index + 60]
    context_terms = ("mudanca", "endereco", "comodo", "cobranca", "autosservico", "reinstalacao")
    return any(term in window for term in context_terms)


def is_change_request(text: str) -> bool:
    normalized = normalize_text(text)
    return any(term in normalized for term in CHANGE_TERMS)


def is_inactivity_status(text: str) -> bool:
    normalized = normalize_text(text)
    return "finalizado por inatividade" in normalized


def is_real_finished_status(text: str) -> bool:
    normalized = normalize_text(text)
    return normalized == "finalizado"


def _mean(series: pd.Series) -> float:
    return float(series.mean()) if len(series) else 0.0


def _median(series: pd.Series) -> float:
    return float(series.median()) if len(series) else 0.0


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round((float(numerator) / float(denominator) * 100), 2) if denominator else 0.0


def _display_value(value: Any, fallback: str) -> str:
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "-"}:
        return fallback
    return text


def _period_info(series: pd.Series | None) -> tuple[str, str, int, str]:
    if series is None or series.empty:
        return "Nao identificado", "Nao identificado", 0, "Nao identificado"
    dates = pd.to_datetime(series, errors="coerce", dayfirst=True)
    dates = dates.dropna()
    if dates.empty:
        return "Nao identificado", "Nao identificado", 0, "Nao identificado"
    start = dates.min()
    end = dates.max()
    days = int((end.normalize() - start.normalize()).days) + 1
    start_text = f"{start:%d/%m/%Y}"
    end_text = f"{end:%d/%m/%Y}"
    if start.month == end.month and start.year == end.year:
        period = f"{start:%d/%m} a {end:%d/%m}"
    else:
        period = f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"
    return start_text, end_text, days, period


def _metric_rows(
    df: pd.DataFrame,
    month: str,
    group_col: str,
    label_col: str,
    total: int,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    grouped = df.groupby(group_col, dropna=False)
    for label, subset in grouped:
        volume = len(subset)
        inactivity = int(subset["_inatividade"].sum())
        rows.append(
            {
                "Mes": month,
                label_col: _display_value(label, "Nao identificado"),
                "Volume": volume,
                "% Volume": _pct(volume, total),
                "Media": _mean(subset["_tma_seconds"]),
                "Mediana": _median(subset["_tma_seconds"]),
                "Inatividade": inactivity,
                "% Inatividade": _pct(inactivity, volume),
            }
        )
    rows.sort(key=lambda item: (item["Inatividade"], item["Media"], item["Volume"]), reverse=True)
    return rows[:top_n] if top_n else rows


def _fee_rows(df: pd.DataFrame, month: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(df)
    for group in TAX_GROUPS:
        subset = df[df["_grupo_taxa"] == group]
        volume = len(subset)
        inactivity = int(subset["_inatividade"].sum()) if volume else 0
        real_finished = int(subset["_finalizado_real"].sum()) if volume else 0
        rows.append(
            {
                "Mes": month,
                "Grupo": group,
                "Volume": volume,
                "TMA": _mean(subset["_tma_seconds"]),
                "Mediana TMA": _median(subset["_tma_seconds"]),
                "TME": _mean(subset["_tme_seconds"]),
                "Mediana TME": _median(subset["_tme_seconds"]),
                "Inatividade": inactivity,
                "% Inatividade": _pct(inactivity, volume),
                "Finalizados reais": real_finished,
                "% Finalizacao real": _pct(real_finished, volume),
            }
        )
    return rows


def analyze_month(
    df: pd.DataFrame,
    month: str,
    attendance_time_col: str,
    wait_time_col: str | None,
    status_col: str | None,
    text_columns: list[str],
    type_col: str | None = None,
    classification_col: str | None = None,
    date_col: str | None = None,
) -> MonthAnalysis:
    if not attendance_time_col:
        raise ValueError("Selecione a coluna de tempo de atendimento.")
    if attendance_time_col not in df.columns:
        raise ValueError("A coluna de tempo de atendimento selecionada nao existe no arquivo.")

    data = df.copy()
    text_columns = [col for col in text_columns if col in data.columns]
    if not text_columns:
        text_columns = [col for col in data.columns if data[col].dtype == "object"]

    has_status = bool(status_col and status_col in data.columns)
    has_type = bool(type_col and type_col in data.columns)
    has_classification = bool(classification_col and classification_col in data.columns)
    has_date = bool(date_col and date_col in data.columns)

    data["_texto_analise"] = data.apply(lambda row: _row_text(row, text_columns), axis=1)
    data["_texto_status"] = data[status_col].apply(normalize_text) if has_status else ""
    data["_status_label"] = data[status_col].apply(lambda value: _display_value(value, "Sem status")) if has_status else "Sem status"
    data["_type_label"] = data[type_col].apply(lambda value: _display_value(value, "Nao identificado")) if has_type else "Nao identificado"
    data["_classification_label"] = (
        data[classification_col].apply(lambda value: _display_value(value, "Nao identificado"))
        if has_classification
        else "Nao identificado"
    )

    data["_tma_seconds"] = data[attendance_time_col].apply(duration_to_seconds)
    if wait_time_col and wait_time_col in data.columns:
        data["_tme_seconds"] = data[wait_time_col].apply(duration_to_seconds)
    else:
        data["_tme_seconds"] = 0

    data["_inatividade"] = data["_texto_status"].apply(is_inactivity_status)
    data["_finalizado_real"] = data["_texto_status"].apply(is_real_finished_status)
    data["_recorte_mudanca"] = data["_texto_analise"].apply(is_change_request)
    data["_grupo_taxa"] = data["_texto_analise"].apply(classify_fee)

    filtered = data[data["_recorte_mudanca"]].copy()
    total_file = len(data)
    total_change = len(filtered)
    total_inactivity = int(filtered["_inatividade"].sum())
    no_inactivity = filtered[~filtered["_inatividade"]]
    period_start, period_end, period_days, period = _period_info(filtered[date_col] if has_date else None)
    real_finished_total = int(filtered["_finalizado_real"].sum()) if total_change else 0

    comparison_row = {
        "Mes": month,
        "Data inicial": period_start,
        "Data final": period_end,
        "Dias analisados": period_days,
        "Total atendimentos arquivo": total_file,
        "Total no recorte": total_change,
        "TMA geral": _mean(filtered["_tma_seconds"]),
        "TME geral": _mean(filtered["_tme_seconds"]),
        "Mediana geral": _median(filtered["_tma_seconds"]),
        "TMA sem inatividade": _mean(no_inactivity["_tma_seconds"]),
        "Mediana sem inatividade": _median(no_inactivity["_tma_seconds"]),
        "Maior tempo": float(filtered["_tma_seconds"].max()) if total_change else 0.0,
        "Inatividade": total_inactivity,
        "% Inatividade": _pct(total_inactivity, total_change),
        "Finalizados reais": real_finished_total,
        "% Finalizacao real": _pct(real_finished_total, total_change),
    }
    period_row = {
        "Mes": month,
        "Data inicial": period_start,
        "Data final": period_end,
        "Dias analisados": period_days,
        "Total atendimentos arquivo": total_file,
        "Total no recorte Mudanca de Endereco + Mudanca de Comodo": total_change,
    }

    return MonthAnalysis(
        month=month,
        period=period,
        period_start=period_start,
        period_end=period_end,
        period_days=period_days,
        total_file=total_file,
        total_change=total_change,
        total_with_fee=int((filtered["_grupo_taxa"] == "Com taxa").sum()) if total_change else 0,
        total_without_fee=int((filtered["_grupo_taxa"] == "Sem taxa").sum()) if total_change else 0,
        total_unknown_fee=int((filtered["_grupo_taxa"] == UNKNOWN_FEE_GROUP).sum()) if total_change else 0,
        general_inactivity=total_inactivity,
        general_inactivity_pct=comparison_row["% Inatividade"],
        general_tma_seconds=comparison_row["TMA geral"],
        general_tme_seconds=comparison_row["TME geral"],
        median_tma_seconds=comparison_row["Mediana geral"],
        tma_without_inactivity_seconds=comparison_row["TMA sem inatividade"],
        median_without_inactivity_seconds=comparison_row["Mediana sem inatividade"],
        max_tma_seconds=comparison_row["Maior tempo"],
        comparison_row=comparison_row,
        period_row=period_row,
        fee_rows=_fee_rows(filtered, month),
        status_rows=_metric_rows(filtered, month, "_status_label", "Status", total_change),
        type_rows=_metric_rows(filtered, month, "_type_label", "Tipo", total_change),
        classification_rows=_metric_rows(filtered, month, "_classification_label", "Classificacao", total_change, top_n=12),
        filtered_data=filtered,
    )


def build_comparison_dataframe(analyses: list[MonthAnalysis]) -> pd.DataFrame:
    return pd.DataFrame([analysis.comparison_row for analysis in analyses])


def build_period_dataframe(analyses: list[MonthAnalysis]) -> pd.DataFrame:
    return pd.DataFrame([analysis.period_row for analysis in analyses])


def build_fee_dataframe(analyses: list[MonthAnalysis]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for analysis in analyses:
        rows.extend(analysis.fee_rows)
    return pd.DataFrame(rows)


def build_status_dataframe(analyses: list[MonthAnalysis]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for analysis in analyses:
        rows.extend(analysis.status_rows)
    return pd.DataFrame(rows)


def build_type_dataframe(analyses: list[MonthAnalysis]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for analysis in analyses:
        rows.extend(analysis.type_rows)
    return pd.DataFrame(rows)


def build_classification_dataframe(analyses: list[MonthAnalysis]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for analysis in analyses:
        rows.extend(analysis.classification_rows)
    return pd.DataFrame(rows)


def build_summary_dataframe(analyses: list[MonthAnalysis]) -> pd.DataFrame:
    return build_comparison_dataframe(analyses)


def build_group_dataframe(analyses: list[MonthAnalysis]) -> pd.DataFrame:
    return build_fee_dataframe(analyses)


def _format_duration_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    formatted = df.copy()
    for column in columns:
        if column in formatted.columns:
            formatted[column] = formatted[column].apply(format_seconds)
    return formatted


def _format_percent_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    formatted = df.copy()
    for column in columns:
        if column in formatted.columns:
            formatted[column] = formatted[column].map(lambda value: f"{float(value):.1f}%")
    return formatted


def format_comparison_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    formatted = _format_duration_columns(
        df,
        (
            "TMA geral",
            "TME geral",
            "Mediana geral",
            "TMA sem inatividade",
            "Mediana sem inatividade",
            "Maior tempo",
        ),
    )
    return _format_percent_columns(formatted, ("% Inatividade", "% Finalizacao real"))


def format_metric_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    formatted = _format_duration_columns(df, ("Media", "Mediana"))
    return _format_percent_columns(formatted, ("% Volume", "% Inatividade"))


def format_fee_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    formatted = _format_duration_columns(df, ("TMA", "Mediana TMA", "TME", "Mediana TME"))
    return _format_percent_columns(formatted, ("% Inatividade", "% Finalizacao real"))


def format_summary_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    return format_comparison_dataframe(df)


def format_group_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    return format_fee_dataframe(df)


def automatic_conclusion(analyses: list[MonthAnalysis], status_df: pd.DataFrame, classification_df: pd.DataFrame) -> str:
    if len(analyses) != 2:
        return "A analise foi processada com sucesso para o periodo informado."

    first, second = analyses
    messages: list[str] = []
    has_low_volume = any(item.total_change < LOW_VOLUME_THRESHOLD for item in analyses)

    if has_low_volume:
        messages.append(LOW_VOLUME_CONCLUSION)
    else:
        higher_tma = first if first.general_tma_seconds >= second.general_tma_seconds else second
        lower_tma = second if higher_tma is first else first
        diff = abs(first.general_tma_seconds - second.general_tma_seconds)
        messages.append(
            f"{higher_tma.month} apresentou maior TMA geral ({format_seconds(higher_tma.general_tma_seconds)}), "
            f"diferenca de {format_seconds(diff)} em relacao a {lower_tma.month}."
        )

    if not has_low_volume and (first.general_inactivity_pct or second.general_inactivity_pct):
        higher_inactivity = first if first.general_inactivity_pct >= second.general_inactivity_pct else second
        messages.append(
            f"A maior inatividade ficou em {higher_inactivity.month}, com "
            f"{higher_inactivity.general_inactivity} casos ({higher_inactivity.general_inactivity_pct:.1f}%)."
        )

    finalized = status_df[status_df["Status"].apply(normalize_text).eq("finalizado")]
    if not has_low_volume and not finalized.empty:
        best_finalized = finalized.sort_values("Mediana").iloc[0]
        messages.append(
            f"Quando o atendimento finaliza de fato, a melhor mediana esta em {best_finalized['Mes']} "
            f"({format_seconds(best_finalized['Mediana'])})."
        )

    if not classification_df.empty:
        bottleneck = classification_df.sort_values(["Inatividade", "% Inatividade", "Media"], ascending=False).iloc[0]
        if bottleneck["Inatividade"] > 0:
            messages.append(
                f"O principal gargalo aparece em {bottleneck['Mes']} na classificacao {bottleneck['Classificacao']}, "
                f"com {int(bottleneck['Inatividade'])} inatividades."
            )

    if sum(item.total_unknown_fee for item in analyses):
        messages.append(
            "A contagem de taxa deve ser lida separadamente do TMA, pois muitos atendimentos tem tag geral de mudanca sem marcacao clara de cobranca."
        )

    return " ".join(messages)
