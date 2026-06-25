from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .analise_atendimento import detect_columns, find_best_column
from .tratamento_tempo import duration_to_seconds, format_seconds


LOW_D44_VOLUME_THRESHOLD = 30
LOW_D44_VOLUME_MESSAGE = "Atencao: baixo volume de atendimentos D44. A analise pode nao representar o periodo."

D44_TERMS = (
    "D44",
    "HSM D44",
    "Regua D44",
    "Regua da cobranca D44",
    "Regua de cobranca 44 dias",
    "Cobranca N2 - Regua da cobranca D44",
    "Cobranca - 2o Nivel",
    "Cobranca - 2 Nivel",
    "Cobranca N2",
    "Disparos de HSM",
    "Conta Disparos de HSM",
)

HSM_OPTIONS = (
    "Pagar agora",
    "Preciso ajuda",
    "Preciso de ajuda",
    "Nao respondeu",
)

PROPOSAL_TERMS = (
    "Proposta sem juros",
    "Proposta com desconto",
    "Nao aceitou proposta",
    "Nao respondeu",
    "Negociacao",
    "Negociacao realizada",
    "Acordo realizado",
    "Boleto enviado",
    "PIX",
    "Codigo de barras",
)

PROPOSAL_GROUPS = (
    "Proposta sem juros",
    "Proposta com desconto",
    "Nao aceitou proposta",
    "Nao respondeu",
)

NEGOTIATION_DONE_TERMS = (
    "Negociacao realizada",
    "Acordo realizado",
    "Proposta aceita",
    "Boleto enviado",
    "PIX gerado",
    "Codigo de barras gerado",
)

ANY_NEGOTIATION_TERMS = (
    "negociacao",
    "negociacao realizada",
    "acordo",
    "proposta aceita",
    "boleto enviado",
    "pix gerado",
    "codigo de barras gerado",
)

CHARGE_TERMS = (
    "Cobranca",
    "Cobranca N2",
    "Cobranca - 2o Nivel",
    "Cobranca - 2 Nivel",
    "Fatura atrasada",
    "Dificuldade em pagar",
    "Pagar agora",
    "Preciso ajuda",
    "PIX",
    "Codigo de barras",
    "Contestar valores",
    "Item da fatura",
    "Valor diferente",
    "Ja paguei",
    "Comprovante",
    "Baixa de pagamento",
    "Negociacao",
    "Negociacao realizada",
    "Nao respondeu",
)

EXTRA_COLUMN_CANDIDATES = {
    "pending_time": ("tempo pendencia", "tempo em pendencia", "pendencia", "tempo pendente"),
    "service": ("servico", "servico atendimento"),
    "subject": ("assunto", "tema"),
    "reason": ("motivo", "causa"),
    "queue": ("fila", "fila atendimento"),
    "category": ("categoria", "categoria atendimento"),
    "account": ("conta", "conta origem"),
    "channel": ("canal", "origem"),
    "active_receptive": ("ativo receptivo", "ativo/receptivo", "direcao", "tipo contato"),
    "recurrence": ("recorrencia", "reincidencia", "rechamada"),
    "tags": ("tag", "tags", "etiqueta", "marcador"),
    "description": ("descricao", "descrição", "observacao", "observação", "comentario"),
}

TEXT_COLUMN_HINTS = (
    "tag",
    "servico",
    "serviço",
    "classificacao",
    "classificação",
    "assunto",
    "motivo",
    "fila",
    "categoria",
    "conta",
    "tipo",
    "descricao",
    "descrição",
    "observacao",
    "observação",
)


@dataclass(frozen=True)
class D44Analysis:
    month: str
    warnings: list[str]
    period: str
    period_start: str
    period_end: str
    period_days: int
    total_file: int
    total_d44: int
    summary_row: dict[str, Any]
    status_rows: list[dict[str, Any]]
    type_rows: list[dict[str, Any]]
    classification_rows: list[dict[str, Any]]
    hsm_rows: list[dict[str, Any]]
    proposal_rows: list[dict[str, Any]]
    proposal_cross_rows: list[dict[str, Any]]
    charge_rows: list[dict[str, Any]]
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


def detect_d44_columns(df: pd.DataFrame) -> dict[str, Any]:
    detected = detect_columns(df)
    columns = [str(col) for col in df.columns]
    for key, candidates in EXTRA_COLUMN_CANDIDATES.items():
        detected[key] = find_best_column(columns, candidates)

    text_columns = set(detected.get("text_columns") or [])
    for key in (
        "tags",
        "service",
        "classification",
        "subject",
        "reason",
        "queue",
        "category",
        "account",
        "type",
        "description",
    ):
        col = detected.get(key)
        if col:
            text_columns.add(col)

    for col in columns:
        normalized = normalize_text(col)
        if any(hint in normalized for hint in TEXT_COLUMN_HINTS):
            text_columns.add(col)

    detected["text_columns"] = [col for col in columns if col in text_columns]
    return detected


def _display_value(value: Any, fallback: str) -> str:
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "-"}:
        return fallback
    return text


def _row_text(row: pd.Series, columns: list[str]) -> str:
    return " | ".join(normalize_text(row.get(col, "")) for col in columns)


def _contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(term) in normalized for term in terms)


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else 0.0


def _mean(series: pd.Series) -> float:
    return float(series.mean()) if len(series) else 0.0


def _median(series: pd.Series) -> float:
    return float(series.median()) if len(series) else 0.0


def _period_info(series: pd.Series | None) -> tuple[str, str, int]:
    if series is None or series.empty:
        return "Nao identificado", "Nao identificado", 0
    dates = pd.to_datetime(series, errors="coerce", dayfirst=True).dropna()
    if dates.empty:
        return "Nao identificado", "Nao identificado", 0
    start = dates.min()
    end = dates.max()
    days = int((end.date() - start.date()).days) + 1
    return f"{start:%d/%m/%Y}", f"{end:%d/%m/%Y}", max(days, 1)


def _base_metrics(subset: pd.DataFrame, total: int) -> dict[str, Any]:
    volume = len(subset)
    inactivity = int(subset["_inatividade"].sum()) if volume else 0
    real_finished = int(subset["_finalizado_real"].sum()) if volume else 0
    return {
        "Volume": volume,
        "% Volume": _pct(volume, total),
        "Finalizados reais": real_finished,
        "% Finalizacao real": _pct(real_finished, volume),
        "Inatividade": inactivity,
        "% Inatividade": _pct(inactivity, volume),
        "TMA": _mean(subset["_tma_seconds"]) if volume else 0,
        "Mediana TMA": _median(subset["_tma_seconds"]) if volume else 0,
        "TME": _mean(subset["_tme_seconds"]) if volume else 0,
        "Mediana TME": _median(subset["_tme_seconds"]) if volume else 0,
    }


def _group_rows(df: pd.DataFrame, group_col: str, label_col: str, total: int, top_n: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if df.empty:
        return rows
    for label, subset in df.groupby(group_col, dropna=False):
        row = {label_col: _display_value(label, "Nao identificado")}
        row.update(_base_metrics(subset, total))
        rows.append(row)
    rows.sort(key=lambda item: (item["Inatividade"], item["Volume"], item["TMA"]), reverse=True)
    return rows[:top_n] if top_n else rows


def _term_rows(df: pd.DataFrame, terms: tuple[str, ...], label_col: str) -> list[dict[str, Any]]:
    total = len(df)
    rows: list[dict[str, Any]] = []
    for term in terms:
        mask = df["_texto_analise"].apply(lambda text: _contains_any(text, [term])) if total else pd.Series(dtype=bool)
        subset = df[mask] if total else df
        row = {label_col: term}
        row.update(_base_metrics(subset, total))
        rows.append(row)
    rows.sort(key=lambda item: item["Volume"], reverse=True)
    return rows


def _hsm_option(text: str) -> str:
    if _contains_any(text, ["Pagar agora"]):
        return "Pagar agora"
    if _contains_any(text, ["Preciso ajuda", "Preciso de ajuda"]):
        return "Preciso ajuda"
    if _contains_any(text, ["Nao respondeu"]):
        return "Nao respondeu"
    return "Outros"


def _hsm_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    total = len(df)
    rows: list[dict[str, Any]] = []
    labels = ["Pagar agora", "Preciso ajuda", "Nao respondeu", "Outros"]
    for label in labels:
        subset = df[df["_hsm_opcao"].eq(label)] if total else df
        row = {"Opcao": label}
        row.update(_base_metrics(subset, total))
        rows.append(row)
    return rows


def _proposal_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    total = len(df)
    rows: list[dict[str, Any]] = []
    for term in PROPOSAL_TERMS:
        mask = df["_texto_analise"].apply(lambda text: _contains_any(text, [term])) if total else pd.Series(dtype=bool)
        subset = df[mask] if total else df
        negotiation_done = int(subset["_negociacao_realizada"].sum()) if len(subset) else 0
        row = {
            "Resultado / proposta": term,
            "Volume": len(subset),
            "% Volume": _pct(len(subset), total),
            "Finalizados reais": int(subset["_finalizado_real"].sum()) if len(subset) else 0,
            "Inatividade": int(subset["_inatividade"].sum()) if len(subset) else 0,
            "% Inatividade": _pct(int(subset["_inatividade"].sum()) if len(subset) else 0, len(subset)),
            "Negociacao realizada": negotiation_done,
            "% Negociacao realizada": _pct(negotiation_done, len(subset)),
            "TMA": _mean(subset["_tma_seconds"]) if len(subset) else 0,
            "Mediana TMA": _median(subset["_tma_seconds"]) if len(subset) else 0,
        }
        rows.append(row)
    rows.sort(key=lambda item: item["Volume"], reverse=True)
    return rows


def _proposal_cross_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in PROPOSAL_GROUPS:
        mask = df["_texto_analise"].apply(lambda text: _contains_any(text, [group])) if len(df) else pd.Series(dtype=bool)
        subset = df[mask] if len(df) else df
        volume = len(subset)
        inactivity = int(subset["_inatividade"].sum()) if volume else 0
        negotiation_done = int(subset["_negociacao_realizada"].sum()) if volume else 0
        any_negotiation = int(subset["_qualquer_negociacao"].sum()) if volume else 0
        rows.append(
            {
                "Grupo": group,
                "Volume": volume,
                "Finalizados reais": int(subset["_finalizado_real"].sum()) if volume else 0,
                "Inatividade": inactivity,
                "% Inatividade": _pct(inactivity, volume),
                "Negociacao realizada": negotiation_done,
                "% Negociacao realizada": _pct(negotiation_done, volume),
                "Qualquer negociacao": any_negotiation,
                "% Qualquer negociacao": _pct(any_negotiation, volume),
            }
        )
    return rows


def _daily_rows(df: pd.DataFrame, date_col: str | None) -> list[dict[str, Any]]:
    if not date_col or date_col not in df.columns or df.empty:
        return []
    data = df.copy()
    data["_data_dia"] = pd.to_datetime(data[date_col], errors="coerce", dayfirst=True).dt.date
    data = data.dropna(subset=["_data_dia"])
    rows: list[dict[str, Any]] = []
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
                "Finalizados reais": int(subset["_finalizado_real"].sum()),
                "Inatividade": inactivity,
                "% Inatividade": _pct(inactivity, volume),
                "Pendentes": int(subset["_pendente"].sum()),
                "Transferidos": int(subset["_transferido"].sum()),
            }
        )
    return rows


def _lookup_volume(rows: list[dict[str, Any]], label_col: str, label: str) -> int:
    for row in rows:
        if normalize_text(row.get(label_col, "")) == normalize_text(label):
            return int(row.get("Volume", 0))
    return 0


def _d44_conclusion(summary: dict[str, Any], hsm_rows: list[dict[str, Any]], proposal_cross_rows: list[dict[str, Any]]) -> str:
    total_file = int(summary["Total de atendimentos no arquivo"])
    total_d44 = int(summary["Total de atendimentos D44"])
    d44_pct = float(summary["% D44 sobre o arquivo"])
    inactivity_pct = float(summary["% Inatividade"])
    finalization_pct = float(summary["% Finalizacao real"])
    paying = _lookup_volume(hsm_rows, "Opcao", "Pagar agora")
    help_count = _lookup_volume(hsm_rows, "Opcao", "Preciso ajuda")
    no_answer = _lookup_volume(hsm_rows, "Opcao", "Nao respondeu")
    negotiation_done = int(summary["Negociacao realizada"])
    negotiation_pct = _pct(negotiation_done, total_d44)
    no_interest = next((row for row in proposal_cross_rows if row["Grupo"] == "Proposta sem juros"), {})
    discount = next((row for row in proposal_cross_rows if row["Grupo"] == "Proposta com desconto"), {})
    no_interest_perf = float(no_interest.get("% Qualquer negociacao", 0))
    discount_perf = float(discount.get("% Qualquer negociacao", 0))

    majority_text = "majoritariamente D44" if total_file and d44_pct >= 50 else "nao e majoritariamente D44"
    response_text = "gerou resposta" if paying + help_count > no_answer else "teve baixa resposta clara"
    conversion_text = "baixa" if negotiation_pct < 20 else "relevante"
    proposal_text = (
        "A proposta sem juros performou melhor que a proposta com desconto."
        if no_interest_perf > discount_perf
        else "A proposta com desconto performou igual ou melhor que a proposta sem juros."
    )
    tma_cause = "inatividade" if inactivity_pct >= 30 else "pendencia" if int(summary.get("Atendimento pendente", 0)) else "tempo operacional"
    bottleneck = "inatividade" if inactivity_pct >= 30 else "conversao em negociacao" if negotiation_pct < 20 else "monitoramento do fluxo posterior ao HSM"

    return (
        f"A base analisada {majority_text}: {total_d44} de {total_file} atendimentos ({d44_pct:.1f}%). "
        f"O HSM {response_text}, com {paying} em Pagar agora, {help_count} em Preciso ajuda e {no_answer} como Nao respondeu. "
        f"A inatividade foi de {inactivity_pct:.1f}% e a finalizacao real foi de {finalization_pct:.1f}%. "
        f"A conversao em negociacao realizada esta {conversion_text}, com {negotiation_done} casos ({negotiation_pct:.1f}%). "
        f"{proposal_text} O TMA esta sendo afetado principalmente por {tma_cause}. "
        f"O principal gargalo encontrado foi {bottleneck}."
    )


def analyze_d44(
    df: pd.DataFrame,
    month: str,
    attendance_time_col: str,
    wait_time_col: str | None,
    status_col: str | None,
    text_columns: list[str],
    type_col: str | None = None,
    classification_col: str | None = None,
    date_col: str | None = None,
    pending_time_col: str | None = None,
) -> D44Analysis:
    warnings: list[str] = []
    if not attendance_time_col or attendance_time_col not in df.columns:
        raise ValueError("Selecione uma coluna valida de tempo de atendimento (TMA) para a analise D44.")

    data = df.copy()
    total_file = len(data)
    text_columns = [col for col in text_columns if col in data.columns]
    if not text_columns:
        text_columns = [col for col in data.columns if data[col].dtype == "object"]
        warnings.append("Campos textuais especificos nao foram identificados; usando colunas de texto disponiveis.")

    if not status_col or status_col not in data.columns:
        warnings.append("Coluna de status nao identificada. Finalizacao, pendencia e inatividade podem ficar zeradas.")
    if not wait_time_col or wait_time_col not in data.columns:
        warnings.append("Coluna de TME nao identificada. TME considerado como 0.")
    if not pending_time_col or pending_time_col not in data.columns:
        warnings.append("Coluna de tempo em pendencia nao identificada. Tempo em pendencia considerado como 0.")
    if not type_col or type_col not in data.columns:
        warnings.append("Coluna de tipo de atendimento nao identificada.")
    if not classification_col or classification_col not in data.columns:
        warnings.append("Coluna de classificacao nao identificada.")
    if not date_col or date_col not in data.columns:
        warnings.append("Coluna de data nao identificada. Analise por dia nao sera gerada.")

    data["_texto_analise"] = data.apply(lambda row: _row_text(row, text_columns), axis=1)
    data["_is_d44"] = data["_texto_analise"].apply(lambda text: _contains_any(text, D44_TERMS))
    filtered = data[data["_is_d44"]].copy()

    if filtered.empty:
        start, end, days = _period_info(data[date_col] if date_col in data.columns else None)
        return D44Analysis(
            month=month,
            warnings=warnings,
            period=f"{start} a {end}" if start != "Nao identificado" else "Nao identificado",
            period_start=start,
            period_end=end,
            period_days=days,
            total_file=total_file,
            total_d44=0,
            summary_row={
                "Mes": month,
                "Total de atendimentos no arquivo": total_file,
                "Total de atendimentos D44": 0,
                "% D44 sobre o arquivo": 0.0,
            },
            status_rows=[],
            type_rows=[],
            classification_rows=[],
            hsm_rows=[],
            proposal_rows=[],
            proposal_cross_rows=[],
            charge_rows=[],
            daily_rows=[],
            conclusion="Nenhum atendimento de Cobranca HSM D44 foi encontrado neste arquivo.",
            prepared_data=filtered,
        )

    filtered["_status_norm"] = filtered[status_col].apply(normalize_text) if status_col in filtered.columns else ""
    filtered["_status_label"] = filtered[status_col].apply(lambda value: _display_value(value, "Sem status")) if status_col in filtered.columns else "Sem status"
    filtered["_type_label"] = filtered[type_col].apply(lambda value: _display_value(value, "Nao identificado")) if type_col in filtered.columns else "Nao identificado"
    filtered["_classification_label"] = filtered[classification_col].apply(lambda value: _display_value(value, "Nao identificado")) if classification_col in filtered.columns else "Nao identificado"
    filtered["_tma_seconds"] = filtered[attendance_time_col].apply(duration_to_seconds)
    filtered["_tme_seconds"] = filtered[wait_time_col].apply(duration_to_seconds) if wait_time_col in filtered.columns else 0
    filtered["_pending_seconds"] = filtered[pending_time_col].apply(duration_to_seconds) if pending_time_col in filtered.columns else 0
    filtered["_finalizado_real"] = filtered["_status_norm"].eq("finalizado")
    filtered["_inatividade"] = filtered["_status_norm"].str.contains("inatividade", regex=False)
    filtered["_pendente"] = filtered["_status_norm"].str.contains("pendente", regex=False)
    filtered["_transferido"] = filtered["_status_norm"].str.contains("transferido", regex=False) | filtered["_status_norm"].str.contains("transfer", regex=False)
    filtered["_em_atendimento"] = filtered["_status_norm"].str.contains("em atendimento", regex=False)
    filtered["_hsm_opcao"] = filtered["_texto_analise"].apply(_hsm_option)
    filtered["_negociacao_realizada"] = filtered["_texto_analise"].apply(lambda text: _contains_any(text, NEGOTIATION_DONE_TERMS))
    filtered["_qualquer_negociacao"] = filtered["_texto_analise"].apply(lambda text: _contains_any(text, ANY_NEGOTIATION_TERMS))

    total_d44 = len(filtered)
    no_inactivity = filtered[~filtered["_inatividade"]]
    start, end, days = _period_info(filtered[date_col] if date_col in filtered.columns else None)
    period = f"{start} a {end}" if start != "Nao identificado" else "Nao identificado"
    type_norm = filtered["_type_label"].apply(normalize_text)

    finalizados = int(filtered["_finalizado_real"].sum())
    inactivity = int(filtered["_inatividade"].sum())
    pending = int(filtered["_pendente"].sum())
    transferred = int(filtered["_transferido"].sum())
    em_atendimento = int(filtered["_em_atendimento"].sum())
    automatic = int(type_norm.str.contains("automatico", regex=False).sum())
    mixed = int(type_norm.str.contains("misto", regex=False).sum())
    human = int(type_norm.str.contains("humano", regex=False).sum())

    hsm_rows = _hsm_rows(filtered)
    proposal_rows = _proposal_rows(filtered)
    proposal_cross_rows = _proposal_cross_rows(filtered)
    charge_rows = _term_rows(filtered, CHARGE_TERMS, "Tag cobranca")

    summary_row = {
        "Mes": month,
        "Total de atendimentos no arquivo": total_file,
        "Total de atendimentos D44": total_d44,
        "% D44 sobre o arquivo": _pct(total_d44, total_file),
        "Periodo analisado": period,
        "Data inicial": start,
        "Data final": end,
        "Dias analisados": days,
        "TMA geral": _mean(filtered["_tma_seconds"]),
        "Mediana TMA": _median(filtered["_tma_seconds"]),
        "TMA sem inatividade": _mean(no_inactivity["_tma_seconds"]),
        "Mediana sem inatividade": _median(no_inactivity["_tma_seconds"]),
        "TME medio": _mean(filtered["_tme_seconds"]),
        "Mediana TME": _median(filtered["_tme_seconds"]),
        "Tempo medio em pendencia": _mean(filtered["_pending_seconds"]),
        "Mediana tempo em pendencia": _median(filtered["_pending_seconds"]),
        "Finalizados reais": finalizados,
        "% Finalizacao real": _pct(finalizados, total_d44),
        "Finalizados por inatividade": inactivity,
        "% Inatividade": _pct(inactivity, total_d44),
        "Atendimento pendente": pending,
        "% Pendente": _pct(pending, total_d44),
        "Transferidos": transferred,
        "% Transferencia": _pct(transferred, total_d44),
        "Em atendimento": em_atendimento,
        "Automatico": automatic,
        "Misto": mixed,
        "Humano": human,
        "Pagar agora": _lookup_volume(hsm_rows, "Opcao", "Pagar agora"),
        "Preciso ajuda": _lookup_volume(hsm_rows, "Opcao", "Preciso ajuda"),
        "Nao respondeu": _lookup_volume(hsm_rows, "Opcao", "Nao respondeu"),
        "Proposta sem juros": _lookup_volume(proposal_rows, "Resultado / proposta", "Proposta sem juros"),
        "Proposta com desconto": _lookup_volume(proposal_rows, "Resultado / proposta", "Proposta com desconto"),
        "Negociacao realizada": int(filtered["_negociacao_realizada"].sum()),
    }

    return D44Analysis(
        month=month,
        warnings=warnings,
        period=period,
        period_start=start,
        period_end=end,
        period_days=days,
        total_file=total_file,
        total_d44=total_d44,
        summary_row=summary_row,
        status_rows=_group_rows(filtered, "_status_label", "Status", total_d44),
        type_rows=_group_rows(filtered, "_type_label", "Tipo", total_d44),
        classification_rows=_group_rows(filtered, "_classification_label", "Classificacao", total_d44, top_n=25),
        hsm_rows=hsm_rows,
        proposal_rows=proposal_rows,
        proposal_cross_rows=proposal_cross_rows,
        charge_rows=charge_rows,
        daily_rows=_daily_rows(filtered, date_col),
        conclusion=_d44_conclusion(summary_row, hsm_rows, proposal_cross_rows),
        prepared_data=filtered,
    )


def build_d44_comparison_dataframe(analyses: list[D44Analysis]) -> pd.DataFrame:
    columns = [
        "Mes",
        "Total de atendimentos no arquivo",
        "Total de atendimentos D44",
        "% D44 sobre o arquivo",
        "Periodo analisado",
        "TMA geral",
        "Mediana TMA",
        "TMA sem inatividade",
        "TME medio",
        "Finalizados reais",
        "% Finalizacao real",
        "Finalizados por inatividade",
        "% Inatividade",
        "Atendimento pendente",
        "Transferidos",
        "Pagar agora",
        "Preciso ajuda",
        "Nao respondeu",
        "Negociacao realizada",
    ]
    rows = [{column: analysis.summary_row.get(column, 0) for column in columns} for analysis in analyses]
    return pd.DataFrame(rows)


def combine_rows(analyses: list[D44Analysis], attribute: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for analysis in analyses:
        rows = getattr(analysis, attribute)
        if rows:
            df = pd.DataFrame(rows)
            df.insert(0, "Mes", analysis.month)
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def format_d44_summary(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    time_cols = (
        "TMA geral",
        "Mediana TMA",
        "TMA sem inatividade",
        "Mediana sem inatividade",
        "TME medio",
        "Mediana TME",
        "Tempo medio em pendencia",
        "Mediana tempo em pendencia",
    )
    for column in time_cols:
        if column in formatted.columns:
            formatted[column] = formatted[column].apply(format_seconds)
    pct_cols = ("% D44 sobre o arquivo", "% Finalizacao real", "% Inatividade", "% Pendente", "% Transferencia")
    for column in pct_cols:
        if column in formatted.columns:
            formatted[column] = formatted[column].map(lambda value: f"{float(value):.1f}%")
    return formatted


def format_d44_metric_table(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    for column in ("TMA", "Mediana TMA", "TME", "Mediana TME"):
        if column in formatted.columns:
            formatted[column] = formatted[column].apply(format_seconds)
    for column in (
        "% Volume",
        "% Finalizacao real",
        "% Inatividade",
        "% Negociacao realizada",
        "% Qualquer negociacao",
    ):
        if column in formatted.columns:
            formatted[column] = formatted[column].map(lambda value: f"{float(value):.1f}%")
    return formatted

