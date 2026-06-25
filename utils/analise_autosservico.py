from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class AutoServiceAnalysis:
    original_data: pd.DataFrame
    prepared_data: pd.DataFrame
    detected_columns: dict[str, str | None]
    summary: dict[str, Any]
    service_df: pd.DataFrame
    type_df: pd.DataFrame
    channel_df: pd.DataFrame
    department_df: pd.DataFrame
    diagnostic: list[str]
    bottlenecks: list[str]
    odd_points: list[str]
    recommendations: list[str]
    conclusion: str
    odd_os_rows: pd.DataFrame
    odd_invoice_rows: pd.DataFrame


def normalize_column(text: Any) -> str:
    if text is None or pd.isna(text):
        return ""
    normalized = str(text).strip().lower()
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-z0-9 ]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def find_column(df: pd.DataFrame, options: list[str]) -> str | None:
    column_map = {normalize_column(column): str(column) for column in df.columns}

    for option in options:
        normalized_option = normalize_column(option)
        if normalized_option in column_map:
            return column_map[normalized_option]

    for normalized_column, original_column in column_map.items():
        for option in options:
            terms = normalize_column(option).split()
            if terms and all(term in normalized_column for term in terms):
                return original_column

    return None


def convert_number(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)

    values = series.astype(str).str.strip()
    values = values.str.replace("R$", "", regex=False)
    values = values.str.replace("%", "", regex=False)
    values = values.str.replace(".", "", regex=False)
    values = values.str.replace(",", ".", regex=False)
    values = values.str.replace(r"[^0-9.\-]", "", regex=True)
    return pd.to_numeric(values, errors="coerce").fillna(0)


def percent(part: float, total: float) -> float:
    if not total:
        return 0.0
    return round(float(part) / float(total) * 100, 1)


def format_number(value: Any) -> str:
    try:
        return f"{int(round(float(value))):,}".replace(",", ".")
    except Exception:
        return str(value)


def format_percent(value: Any) -> str:
    try:
        return f"{float(value):.1f}%".replace(".", ",")
    except Exception:
        return "0,0%"


def format_money(value: Any) -> str:
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def read_auto_service_file(uploaded_file: object) -> pd.DataFrame:
    filename = getattr(uploaded_file, "name", "").lower()
    raw = bytes(uploaded_file.getvalue()) if hasattr(uploaded_file, "getvalue") else uploaded_file.read()

    if filename.endswith(".csv"):
        for encoding in ("utf-8", "latin1", "cp1252"):
            try:
                return _cleanup_dataframe(pd.read_csv(BytesIO(raw), sep=None, engine="python", encoding=encoding))
            except Exception:
                continue
        raise ValueError("Nao foi possivel ler o CSV. Verifique encoding e separador.")

    if filename.endswith((".xlsx", ".xls")):
        return _cleanup_dataframe(pd.read_excel(BytesIO(raw)))

    raise ValueError("Formato nao suportado. Use CSV, XLSX ou XLS.")


def _cleanup_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned = cleaned.dropna(axis=1, how="all")
    cleaned.columns = [str(column).replace("\ufeff", "").strip() for column in cleaned.columns]
    unnamed = [column for column in cleaned.columns if str(column).lower().startswith("unnamed:")]
    if unnamed:
        cleaned = cleaned.drop(columns=unnamed)
    return cleaned


def detect_auto_service_columns(df: pd.DataFrame) -> dict[str, str | None]:
    return {
        "mes": find_column(df, ["AnoMes do atendimento", "AnoMes", "AnoMes atendimento", "Mes", "Competencia"]),
        "departamento": find_column(df, ["Servico ASC ou Depto HD", "Departamento", "Equipe", "Setor"]),
        "servico": find_column(df, ["Autosservico", "Servico", "Assist"]),
        "tipo": find_column(df, ["Tipo do atendimento", "Tipo Atendimento", "Tipo"]),
        "canal": find_column(df, ["Integracao", "Canal", "Origem", "Plataforma"]),
        "atendimentos": find_column(df, ["Total Autosservico", "Total de Atendimentos", "Atendimentos", "Acionamentos"]),
        "csat_total": find_column(df, ["Teve avaliacao CSAT", "Avaliacoes CSAT", "CSAT total"]),
        "media_csat": find_column(df, ["Media CSAT"]),
        "csat_pos_percent": find_column(df, ["%CSAT 4 ou 5", "% CSAT 4 ou 5"]),
        "csat_pos": find_column(df, ["Teve nota CSAT 4 ou 5", "CSAT 4 ou 5", "CSAT Positivo"]),
        "csat_neg_percent": find_column(df, ["%CSAT <= 3", "% CSAT <= 3"]),
        "csat_neg": find_column(df, ["Teve nota CSAT <= 3", "CSAT <= 3", "CSAT Negativo"]),
        "os_geradas": find_column(df, ["OS geradas", "Ordens geradas"]),
        "os_executadas": find_column(df, ["OS executadas", "Ordens executadas"]),
        "perc_os_executadas": find_column(df, ["%OS executadas", "% OS executadas"]),
        "faturas_geradas": find_column(df, ["Faturas geradas", "Boletos gerados"]),
        "faturas_pagas": find_column(df, ["Faturas pagas", "Boletos pagos"]),
        "perc_faturas_pagas": find_column(df, ["%Faturas pagas", "% Faturas pagas"]),
        "boletos_isentos": find_column(df, ["Teve o boleto isento", "Boletos isentos", "Boleto isento", "Isentos"]),
        "valor_total": find_column(df, ["Valor total das faturas", "Valor Total Faturas", "Valor total", "Valor"]),
    }


def prepare_auto_service_base(df: pd.DataFrame, columns: dict[str, str | None]) -> pd.DataFrame:
    base = df.copy()
    numeric_keys = [
        "atendimentos",
        "csat_total",
        "csat_pos",
        "csat_neg",
        "os_geradas",
        "os_executadas",
        "faturas_geradas",
        "faturas_pagas",
        "boletos_isentos",
        "valor_total",
    ]
    text_keys = ["mes", "departamento", "servico", "tipo", "canal"]

    for key in numeric_keys:
        column = columns.get(key)
        base[f"__{key}"] = convert_number(base[column]) if column and column in base.columns else 0

    for key in text_keys:
        column = columns.get(key)
        base[f"__{key}"] = base[column].fillna("Nao informado").astype(str) if column and column in base.columns else "Nao informado"

    return base


def calculate_summary(base: pd.DataFrame) -> dict[str, Any]:
    total_records = len(base)
    total_attendances = float(base["__atendimentos"].sum())
    os_created = float(base["__os_geradas"].sum())
    os_executed = float(base["__os_executadas"].sum())
    invoices_created = float(base["__faturas_geradas"].sum())
    invoices_paid = float(base["__faturas_pagas"].sum())
    exempt_bills = float(base["__boletos_isentos"].sum())
    total_value = float(base["__valor_total"].sum())
    csat_total = float(base["__csat_total"].sum())
    csat_pos = float(base["__csat_pos"].sum())
    csat_neg = float(base["__csat_neg"].sum())

    if csat_total == 0 and (csat_pos + csat_neg) > 0:
        csat_total = csat_pos + csat_neg

    return {
        "Registros": total_records,
        "Atendimentos": total_attendances,
        "OS geradas": os_created,
        "OS executadas": os_executed,
        "% OS executadas": percent(os_executed, os_created),
        "Faturas geradas": invoices_created,
        "Faturas pagas": invoices_paid,
        "% Faturas pagas": percent(invoices_paid, invoices_created),
        "Boletos isentos": exempt_bills,
        "Valor total": total_value,
        "Avaliacoes CSAT": csat_total,
        "CSAT positivo": csat_pos,
        "CSAT negativo": csat_neg,
        "% CSAT positivo": percent(csat_pos, csat_total),
        "% CSAT negativo": percent(csat_neg, csat_total),
    }


def summary_by_group(base: pd.DataFrame, group: str) -> pd.DataFrame:
    table = (
        base.groupby(group, dropna=False)
        .agg(
            Atendimentos=("__atendimentos", "sum"),
            OS_geradas=("__os_geradas", "sum"),
            OS_executadas=("__os_executadas", "sum"),
            Faturas_geradas=("__faturas_geradas", "sum"),
            Faturas_pagas=("__faturas_pagas", "sum"),
            Boletos_isentos=("__boletos_isentos", "sum"),
            Valor_total=("__valor_total", "sum"),
            Avaliacoes_CSAT=("__csat_total", "sum"),
            CSAT_positivo=("__csat_pos", "sum"),
            CSAT_negativo=("__csat_neg", "sum"),
        )
        .reset_index()
    )
    total_attendances = table["Atendimentos"].sum()
    table["% volume"] = table["Atendimentos"].apply(lambda value: percent(value, total_attendances))
    table["% OS executadas"] = table.apply(lambda row: percent(row["OS_executadas"], row["OS_geradas"]), axis=1)
    table["% Faturas pagas"] = table.apply(lambda row: percent(row["Faturas_pagas"], row["Faturas_geradas"]), axis=1)
    table["% CSAT positivo"] = table.apply(lambda row: percent(row["CSAT_positivo"], row["Avaliacoes_CSAT"]), axis=1)
    return table.sort_values("Atendimentos", ascending=False)


def format_auto_service_table(table: pd.DataFrame) -> pd.DataFrame:
    formatted = table.copy()
    formatted = formatted.rename(
        columns={
            "__servico": "Servico",
            "__tipo": "Tipo",
            "__canal": "Canal",
            "__departamento": "Departamento",
        }
    )
    for column in formatted.columns:
        if str(column).startswith("%"):
            formatted[column] = formatted[column].apply(format_percent)
    for column in [
        "Atendimentos",
        "OS_geradas",
        "OS_executadas",
        "Faturas_geradas",
        "Faturas_pagas",
        "Boletos_isentos",
        "Avaliacoes_CSAT",
        "CSAT_positivo",
        "CSAT_negativo",
    ]:
        if column in formatted.columns:
            formatted[column] = formatted[column].apply(format_number)
    if "Valor_total" in formatted.columns:
        formatted["Valor_total"] = formatted["Valor_total"].apply(format_money)
    return formatted


def build_diagnostic(summary: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    if summary["% OS executadas"] < 60:
        texts.append(
            f"A taxa de execucao de OS esta baixa: {format_percent(summary['% OS executadas'])}. "
            "Isso indica que a solicitacao entra, mas nao fecha bem na execucao."
        )
    else:
        texts.append(
            f"A taxa de execucao de OS esta em {format_percent(summary['% OS executadas'])}. "
            "O processo operacional esta em nivel aceitavel, mas ainda precisa ser acompanhado."
        )

    if summary["% Faturas pagas"] < 30:
        texts.append(
            f"A taxa de faturas pagas esta muito baixa: {format_percent(summary['% Faturas pagas'])}. "
            "Esse e um gargalo financeiro claro: gera fatura, mas o cliente nao paga ou o fluxo nao conduz bem ao pagamento."
        )
    else:
        texts.append(
            f"A taxa de faturas pagas esta em {format_percent(summary['% Faturas pagas'])}. "
            "O fluxo financeiro apresenta melhor aderencia."
        )

    if summary["Avaliacoes CSAT"] == 0:
        texts.append("Nao ha CSAT registrado. Sem isso, o canal fica cego em satisfacao.")
    elif summary["% CSAT positivo"] >= 90:
        texts.append(
            f"O CSAT positivo esta alto: {format_percent(summary['% CSAT positivo'])}. "
            "A satisfacao aparente e boa, mas precisa ser analisada junto com execucao de OS e pagamento."
        )
    else:
        texts.append(
            f"O CSAT positivo esta em {format_percent(summary['% CSAT positivo'])}. "
            "Existe sinal de atrito na experiencia do cliente."
        )
    return texts


def build_bottlenecks(summary: dict[str, Any], channel_df: pd.DataFrame, department_df: pd.DataFrame) -> list[str]:
    bottlenecks: list[str] = []
    if summary["% OS executadas"] < 60:
        bottlenecks.append("Baixa execucao de OS. O processo gera ordem, mas nao garante conclusao operacional.")
    if summary["% Faturas pagas"] < 30:
        bottlenecks.append("Baixa taxa de pagamento. O cliente pode estar saindo do fluxo antes de pagar ou a orientacao esta fraca.")
    if summary["Boletos isentos"] > 0:
        bottlenecks.append(
            f"Volume de boletos isentos: {format_number(summary['Boletos isentos'])}. "
            "E necessario separar isencao legitima de falha no fluxo de cobranca."
        )
    if not channel_df.empty:
        channel = channel_df.sort_values("% OS executadas", ascending=True).iloc[0]
        bottlenecks.append(
            f"No canal {channel['__canal']}, a execucao de OS esta em {format_percent(channel['% OS executadas'])}."
        )
    if not department_df.empty:
        csat_df = department_df[department_df["Avaliacoes_CSAT"] > 0].sort_values("% CSAT positivo", ascending=True)
        if not csat_df.empty:
            row = csat_df.iloc[0]
            bottlenecks.append(
                f"O menor CSAT positivo por equipe/departamento aparece em {row['__departamento']}, "
                f"com {format_percent(row['% CSAT positivo'])}."
            )
    return bottlenecks or ["Nao foram identificados gargalos criticos com as colunas disponiveis."]


def build_odd_points(base: pd.DataFrame) -> tuple[list[str], pd.DataFrame, pd.DataFrame]:
    points: list[str] = []
    odd_os_rows = base[base["__os_geradas"] > base["__atendimentos"]]
    if not odd_os_rows.empty:
        points.append(
            f"Existem {len(odd_os_rows)} linha(s) em que OS geradas e maior que o total de atendimentos. "
            "Pode ser duplicidade, reabertura, multiplas OS por cliente ou erro de integracao."
        )

    missing_csat = base[(base["__atendimentos"] > 0) & (base["__csat_total"] == 0)]
    if not missing_csat.empty:
        points.append(f"Existem {len(missing_csat)} linha(s) com atendimento, mas sem CSAT registrado.")

    value_without_invoice = base[(base["__valor_total"] > 0) & (base["__faturas_geradas"] == 0)]
    if not value_without_invoice.empty:
        points.append(f"Existem {len(value_without_invoice)} linha(s) com valor de fatura, mas sem fatura gerada informada.")

    odd_invoice_rows = base[(base["__faturas_geradas"] > 0) & (base["__faturas_pagas"] == 0)]
    if not odd_invoice_rows.empty:
        points.append(f"Existem {len(odd_invoice_rows)} linha(s) com fatura gerada e nenhuma fatura paga.")

    return points or ["Nenhum ponto estranho critico foi identificado na base."], odd_os_rows, odd_invoice_rows


def build_conclusion(summary: dict[str, Any]) -> str:
    if summary["% OS executadas"] < 60 and summary["% Faturas pagas"] < 30:
        return (
            "O autosservico esta funcionando como entrada de solicitacao, mas ainda nao fecha bem o processo. "
            "O cliente solicita, a OS e a fatura sao geradas, mas existe perda forte na execucao e no pagamento."
        )
    if summary["% OS executadas"] >= 60 and summary["% Faturas pagas"] < 30:
        return "A execucao operacional esta melhor que o financeiro. O principal problema esta no pagamento das faturas."
    if summary["% OS executadas"] < 60 and summary["% Faturas pagas"] >= 30:
        return "O pagamento nao e o maior problema. O gargalo principal esta na execucao das OS."
    return "O fluxo apresenta desempenho geral aceitavel. Mesmo assim, e necessario acompanhar canais, departamentos e pontos sem CSAT."


def build_recommendations() -> list[str]:
    return [
        "Criar funil fixo: solicitacao feita -> OS gerada -> fatura gerada -> fatura paga/isenta -> OS executada -> cliente avaliou.",
        "Separar OS executada, pendente, cancelada e reagendada.",
        "Separar fatura paga, fatura em aberto, fatura isenta e fatura cancelada.",
        "Criar alerta para OS gerada e nao executada dentro do prazo esperado.",
        "Criar alerta para fatura gerada e nao paga.",
        "Medir CSAT em todos os canais, principalmente no App Minha Valenet.",
        "Auditar mudanca de endereco separadamente, pois tende a concentrar volume e falha operacional.",
        "Revisar a comunicacao enviada ao cliente sobre valor, prazo, pagamento e proxima etapa.",
        "Investigar linhas em que OS geradas e maior que atendimentos.",
        "Criar painel comparando App Minha Valenet x WhatsApp x Atendimento Humano.",
    ]


def analyze_auto_service(df: pd.DataFrame) -> AutoServiceAnalysis:
    columns = detect_auto_service_columns(df)
    base = prepare_auto_service_base(df, columns)
    summary = calculate_summary(base)
    service_df = summary_by_group(base, "__servico")
    type_df = summary_by_group(base, "__tipo")
    channel_df = summary_by_group(base, "__canal")
    department_df = summary_by_group(base, "__departamento")
    odd_points, odd_os_rows, odd_invoice_rows = build_odd_points(base)
    return AutoServiceAnalysis(
        original_data=df,
        prepared_data=base,
        detected_columns=columns,
        summary=summary,
        service_df=service_df,
        type_df=type_df,
        channel_df=channel_df,
        department_df=department_df,
        diagnostic=build_diagnostic(summary),
        bottlenecks=build_bottlenecks(summary, channel_df, department_df),
        odd_points=odd_points,
        recommendations=build_recommendations(),
        conclusion=build_conclusion(summary),
        odd_os_rows=odd_os_rows,
        odd_invoice_rows=odd_invoice_rows,
    )
