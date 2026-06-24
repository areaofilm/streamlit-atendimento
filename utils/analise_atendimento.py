from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .tratamento_tempo import duration_to_seconds, format_seconds


UNKNOWN_FEE_GROUP = "Sem identificacao clara de taxa"
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
    "date": ("data criacao", "data de criacao", "data abertura", "abertura", "criado em"),
}


@dataclass(frozen=True)
class MonthAnalysis:
    month: str
    total_file: int
    total_change: int
    total_with_fee: int
    total_without_fee: int
    total_unknown_fee: int
    general_inactivity: int
    general_inactivity_pct: float
    general_tma_seconds: float
    general_tme_seconds: float
    change_tma_seconds: float
    change_tme_seconds: float
    summary_row: dict[str, Any]
    group_rows: list[dict[str, Any]]
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


def is_inactivity_text(text: str) -> bool:
    normalized = normalize_text(text)
    return "finalizado por inatividade" in normalized or "inatividade" in normalized


def is_finished_text(text: str) -> bool:
    normalized = normalize_text(text)
    return any(term in normalized for term in ("finalizado", "concluido", "encerrado", "resolvido"))


def _mean(series: pd.Series) -> float:
    return float(series.mean()) if len(series) else 0.0


def _median(series: pd.Series) -> float:
    return float(series.median()) if len(series) else 0.0


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round((float(numerator) / float(denominator) * 100), 2) if denominator else 0.0


def analyze_month(
    df: pd.DataFrame,
    month: str,
    attendance_time_col: str,
    wait_time_col: str | None,
    status_col: str | None,
    text_columns: list[str],
) -> MonthAnalysis:
    if not attendance_time_col:
        raise ValueError("Selecione a coluna de tempo de atendimento.")
    if attendance_time_col not in df.columns:
        raise ValueError("A coluna de tempo de atendimento selecionada nao existe no arquivo.")

    data = df.copy()
    text_columns = [col for col in text_columns if col in data.columns]
    if not text_columns:
        text_columns = [col for col in data.columns if data[col].dtype == "object"]

    status_text = data[status_col].apply(normalize_text) if status_col in data.columns else ""
    data["_texto_analise"] = data.apply(lambda row: _row_text(row, text_columns), axis=1)
    if isinstance(status_text, pd.Series):
        data["_texto_status"] = status_text
    else:
        data["_texto_status"] = ""

    data["_tma_seconds"] = data[attendance_time_col].apply(duration_to_seconds)
    if wait_time_col and wait_time_col in data.columns:
        data["_tme_seconds"] = data[wait_time_col].apply(duration_to_seconds)
    else:
        data["_tme_seconds"] = 0

    data["_inatividade"] = (
        data["_texto_status"].apply(is_inactivity_text) | data["_texto_analise"].apply(is_inactivity_text)
    )
    data["_finalizado"] = data["_texto_status"].apply(is_finished_text)
    data["_recorte_mudanca"] = data["_texto_analise"].apply(is_change_request)
    data["_grupo_taxa"] = data["_texto_analise"].apply(classify_fee)

    filtered = data[data["_recorte_mudanca"]].copy()
    total_file = len(data)
    total_change = len(filtered)
    general_inactivity = int(data["_inatividade"].sum())

    summary_row = {
        "Mes": month,
        "Total do arquivo": total_file,
        "Total mudanca endereco + comodo": total_change,
        "TMA geral": _mean(data["_tma_seconds"]),
        "TME geral": _mean(data["_tme_seconds"]),
        "Inatividade geral": general_inactivity,
        "% inatividade geral": _pct(general_inactivity, total_file),
    }

    group_rows: list[dict[str, Any]] = []
    for group in TAX_GROUPS:
        subset = filtered[filtered["_grupo_taxa"] == group]
        volume = len(subset)
        inactivity = int(subset["_inatividade"].sum()) if volume else 0
        finished = int(subset["_finalizado"].sum()) if volume else 0
        group_rows.append(
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
                "Finalizados": finished,
                "% Finalizacao": _pct(finished, volume),
            }
        )

    return MonthAnalysis(
        month=month,
        total_file=total_file,
        total_change=total_change,
        total_with_fee=int((filtered["_grupo_taxa"] == "Com taxa").sum()) if total_change else 0,
        total_without_fee=int((filtered["_grupo_taxa"] == "Sem taxa").sum()) if total_change else 0,
        total_unknown_fee=int((filtered["_grupo_taxa"] == UNKNOWN_FEE_GROUP).sum()) if total_change else 0,
        general_inactivity=general_inactivity,
        general_inactivity_pct=summary_row["% inatividade geral"],
        general_tma_seconds=summary_row["TMA geral"],
        general_tme_seconds=summary_row["TME geral"],
        change_tma_seconds=_mean(filtered["_tma_seconds"]),
        change_tme_seconds=_mean(filtered["_tme_seconds"]),
        summary_row=summary_row,
        group_rows=group_rows,
        filtered_data=filtered,
    )


def build_summary_dataframe(analyses: list[MonthAnalysis]) -> pd.DataFrame:
    return pd.DataFrame([analysis.summary_row for analysis in analyses])


def build_group_dataframe(analyses: list[MonthAnalysis]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for analysis in analyses:
        rows.extend(analysis.group_rows)
    return pd.DataFrame(rows)


def format_summary_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    for column in ("TMA geral", "TME geral"):
        formatted[column] = formatted[column].apply(format_seconds)
    formatted["% inatividade geral"] = formatted["% inatividade geral"].map(lambda value: f"{value:.2f}%")
    return formatted


def format_group_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    for column in ("TMA", "Mediana TMA", "TME", "Mediana TME"):
        formatted[column] = formatted[column].apply(format_seconds)
    for column in ("% Inatividade", "% Finalizacao"):
        formatted[column] = formatted[column].map(lambda value: f"{value:.2f}%")
    return formatted


def automatic_conclusion(analyses: list[MonthAnalysis], group_df: pd.DataFrame) -> str:
    if len(analyses) != 2:
        return "A analise foi processada com sucesso para o periodo informado."

    first, second = analyses
    messages: list[str] = []

    if first.general_tme_seconds == 0 and second.general_tme_seconds == 0:
        messages.append("Nao houve impacto relevante de fila/espera nos arquivos analisados, pois o TME geral ficou zerado.")
    else:
        higher_tme = max(analyses, key=lambda item: item.general_tme_seconds)
        messages.append(
            f"O maior TME geral foi observado em {higher_tme.month}, com {format_seconds(higher_tme.general_tme_seconds)}."
        )

    diff = abs(first.change_tma_seconds - second.change_tma_seconds)
    if diff > 0:
        higher_tma = first if first.change_tma_seconds > second.change_tma_seconds else second
        messages.append(
            f"No recorte de mudanca de endereco + comodo, {higher_tma.month} apresentou TMA maior "
            f"({format_seconds(higher_tma.change_tma_seconds)}), diferenca de {format_seconds(diff)}."
        )

    if not group_df.empty:
        active_groups = group_df[group_df["Volume"] > 0]
        if not active_groups.empty:
            highest_inactivity = active_groups.sort_values("% Inatividade", ascending=False).iloc[0]
            if highest_inactivity["% Inatividade"] > 0:
                messages.append(
                    f"O maior percentual de inatividade no recorte esta em {highest_inactivity['Mes']} "
                    f"no grupo {highest_inactivity['Grupo']}, com {highest_inactivity['% Inatividade']:.2f}%."
                )

            without_fee = active_groups[active_groups["Grupo"] == "Sem taxa"]
            if not without_fee.empty and without_fee["% Inatividade"].max() <= 10:
                messages.append("Os atendimentos sem taxa apresentam baixa inatividade no periodo analisado.")

    unknown_total = sum(analysis.total_unknown_fee for analysis in analyses)
    change_total = sum(analysis.total_change for analysis in analyses)
    if change_total and unknown_total / change_total >= 0.25:
        messages.append(
            "Ha volume relevante sem identificacao clara de taxa; recomenda-se melhorar a marcacao nos campos de tags, assunto ou classificacao."
        )

    if not messages:
        messages.append("Os indicadores ficaram estaveis entre os meses analisados, sem variacao critica aparente.")

    return " ".join(messages)
