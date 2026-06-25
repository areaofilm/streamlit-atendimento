from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import pandas as pd


APPROVED_THRESHOLD = 85
ATTENTION_THRESHOLD = 70
AUTO_MODEL = "auto"
PREFERRED_TEXT_MODELS = (
    "gpt-4.1-mini",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1",
    "gpt-5-mini",
    "gpt-5",
    "o4-mini",
    "o3-mini",
)
NON_TEXT_MODEL_PARTS = (
    "audio",
    "embedding",
    "image",
    "moderation",
    "realtime",
    "search",
    "sora",
    "speech",
    "tts",
    "transcribe",
    "translation",
    "video",
    "vision",
    "whisper",
)
DOCUMENT_RULE_MARKERS = (
    "deve",
    "obrigatorio",
    "obrigatoria",
    "necessario",
    "necessaria",
    "validar",
    "confirmar",
    "identificar",
    "informar",
    "orientar",
    "ofertar",
    "oferecer",
    "registrar",
    "proibido",
    "proibida",
    "frase de risco",
    "frase proibida",
    "nao usar",
    "evitar",
)
DOCUMENT_NOISE_HEADINGS = {
    "cronograma",
    "quebra",
    "login e logout",
    "dados cadastrais",
    "registrando a",
}


DEFAULT_CRITERIA: list[dict[str, Any]] = [
    {
        "nome": "Saudacao inicial",
        "tipo": "obrigatorio",
        "peso": 10,
        "termos": ["bom dia", "boa tarde", "boa noite", "ola", "oi"],
        "sugestao": "Iniciar com saudacao cordial e disponibilidade para ajudar.",
    },
    {
        "nome": "Cliente identificado",
        "tipo": "obrigatorio",
        "peso": 12,
        "termos": ["cpf", "cnpj", "codigo do cliente", "nome completo", "titular", "contrato"],
        "sugestao": "Confirmar dados minimos do cliente antes de orientar ou negociar.",
    },
    {
        "nome": "Acolhimento ou empatia",
        "tipo": "obrigatorio",
        "peso": 12,
        "termos": ["entendo", "compreendo", "sinto muito", "vou te ajudar", "posso verificar"],
        "sugestao": "Adicionar acolhimento antes de negar, corrigir ou transferir a demanda.",
    },
    {
        "nome": "Oferta de negociacao",
        "tipo": "obrigatorio",
        "peso": 18,
        "termos": ["negociacao", "parcelamento", "opcoes disponiveis", "regularizacao", "acordo", "segunda via"],
        "sugestao": "Apresentar uma opcao clara de regularizacao ou proximo passo para o cliente.",
    },
    {
        "nome": "Orientacao clara sobre prazo",
        "tipo": "obrigatorio",
        "peso": 16,
        "termos": ["prazo", "ate", "em ate", "dias uteis", "vencimento", "data limite"],
        "sugestao": "Informar prazo, data limite ou tempo esperado de retorno de forma objetiva.",
    },
    {
        "nome": "Encerramento cordial",
        "tipo": "obrigatorio",
        "peso": 8,
        "termos": ["posso ajudar em algo mais", "algo mais", "agradeco", "obrigado", "tenha um bom"],
        "sugestao": "Encerrar confirmando se ha mais alguma duvida e agradecendo o contato.",
    },
    {
        "nome": "Frase de risco: negativa seca",
        "tipo": "proibido",
        "peso": 12,
        "termos": [
            "nao posso gerar outra fatura",
            "nao consigo gerar outra fatura",
            "nao posso fazer nada",
            "isso nao e possivel",
        ],
        "sugestao": (
            "Substituir por: No momento nao consigo emitir uma nova fatura com prazo estendido, "
            "mas posso verificar as opcoes disponiveis para regularizacao."
        ),
    },
    {
        "nome": "Frase de risco: transferencia de culpa",
        "tipo": "proibido",
        "peso": 12,
        "termos": ["voce tem que", "problema seu", "nao e comigo", "deveria ter pago"],
        "sugestao": "Trocar por uma orientacao neutra, objetiva e com alternativa de solucao.",
    },
]

DEFAULT_CRITERIA_JSON = json.dumps({"criterios": DEFAULT_CRITERIA}, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class CriterionMatch:
    term: str
    snippet: str


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


def parse_criteria_json(raw_json: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw_json or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON dos criterios invalido: {exc}") from exc

    criteria = payload.get("criterios") if isinstance(payload, dict) else payload
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("Informe uma lista de criterios ou um objeto com a chave 'criterios'.")

    parsed: list[dict[str, Any]] = []
    for index, item in enumerate(criteria, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Criterio {index} precisa ser um objeto JSON.")
        name = str(item.get("nome", "")).strip()
        kind = normalize_text(item.get("tipo", "obrigatorio"))
        terms = [str(term).strip() for term in item.get("termos", []) if str(term).strip()]
        weight = float(item.get("peso", 0))
        if not name:
            raise ValueError(f"Criterio {index} esta sem nome.")
        if kind not in {"obrigatorio", "proibido"}:
            raise ValueError(f"Criterio '{name}' deve ter tipo 'obrigatorio' ou 'proibido'.")
        if weight <= 0:
            raise ValueError(f"Criterio '{name}' precisa ter peso maior que zero.")
        if not terms:
            raise ValueError(f"Criterio '{name}' precisa ter pelo menos um termo.")
        parsed.append(
            {
                "nome": name,
                "tipo": kind,
                "peso": weight,
                "termos": terms,
                "sugestao": str(item.get("sugestao", "")).strip(),
            }
        )
    return parsed


def parse_criteria_document(raw_text: str) -> list[dict[str, Any]]:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("O arquivo de criterios esta vazio ou nao teve texto extraido.")

    json_candidate = _extract_json_candidate(text)
    if json_candidate:
        try:
            return parse_criteria_json(json_candidate)
        except ValueError:
            pass

    criteria: list[dict[str, Any]] = []
    for line in _criteria_lines(text):
        criterion = _criterion_from_line(line)
        if criterion:
            criteria.append(criterion)

    if not criteria:
        raise ValueError(
            "Nao consegui identificar criterios no PDF/TXT. Use linhas objetivas ou mantenha o cadastro em JSON."
        )
    return criteria


def read_uploaded_text(uploaded_file: Any) -> str:
    if uploaded_file is None:
        return ""

    file_name = str(getattr(uploaded_file, "name", "")).lower()
    file_bytes = uploaded_file.getvalue()
    if file_name.endswith(".pdf"):
        return _read_pdf_text(file_bytes)

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="ignore")


def _extract_json_candidate(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _criteria_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^\s*(?:[-*•]|\d+[\).:-])\s*", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 8:
            continue
        if _looks_like_document_heading(line):
            continue
        lines.append(line)
    return lines


def _criterion_from_line(line: str) -> dict[str, Any] | None:
    normalized = normalize_text(line)
    name, terms_text, has_separator = _split_criterion_line(line)
    has_quoted_terms = bool(re.search(r'"[^"]+"|\'[^\']+\'', line))
    has_rule_marker = any(marker in normalized for marker in DOCUMENT_RULE_MARKERS)
    has_term_list = bool(re.search(r"[,;]", terms_text))
    looks_structured = has_separator and (has_term_list or has_quoted_terms or has_rule_marker)
    if not (looks_structured or has_quoted_terms or has_rule_marker):
        return None

    is_forbidden = any(
        marker in normalized
        for marker in (
            "frase de risco",
            "frase proibida",
            "proibido",
            "nao conforme",
            "nao usar",
            "evitar",
            "risco",
        )
    )
    kind = "proibido" if is_forbidden else "obrigatorio"
    weight = 12 if is_forbidden else 10
    if not terms_text and has_rule_marker and not has_quoted_terms:
        terms = _terms_from_rule_sentence(line)
    else:
        terms = _terms_from_text(terms_text or line)
    if not terms:
        return None
    return {
        "nome": name[:90],
        "tipo": kind,
        "peso": weight,
        "termos": terms,
        "sugestao": _suggestion_for_document_criterion(kind, name),
    }


def _looks_like_document_heading(line: str) -> bool:
    normalized = normalize_text(line)
    if normalized in {"criterios", "criterios os pro", "checklist", "regras"} | DOCUMENT_NOISE_HEADINGS:
        return True
    has_punctuation = bool(re.search(r"[:;,.!?\"']", line))
    word_count = len(normalized.split())
    has_rule_marker = any(marker in normalized for marker in DOCUMENT_RULE_MARKERS)
    return not has_punctuation and word_count <= 5 and not has_rule_marker


def _split_criterion_line(line: str) -> tuple[str, str, bool]:
    for separator in (":", "-", "–", "—"):
        if separator in line:
            left, right = line.split(separator, 1)
            if left.strip() and right.strip():
                return left.strip(), right.strip(), True
    return line.strip(), "", False


def _terms_from_text(text: str) -> list[str]:
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
    terms = [left or right for left, right in quoted]
    if not terms:
        chunks = re.split(r";|,|\bou\b|\be\b", text, flags=re.IGNORECASE)
        terms = [chunk.strip(" .:-") for chunk in chunks]
    clean_terms = []
    for term in terms:
        cleaned = re.sub(r"\s+", " ", term).strip()
        if len(cleaned) >= 3 and normalize_text(cleaned) not in {"deve", "ter", "usar", "conter"}:
            clean_terms.append(cleaned)
    return clean_terms[:12]


def _terms_from_rule_sentence(text: str) -> list[str]:
    normalized = normalize_text(text)
    normalized = re.sub(
        r"\b(deve|obrigatorio|obrigatoria|necessario|necessaria|validar|confirmar|identificar|informar|orientar|ofertar|oferecer|registrar)\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    stop_words = {
        "a",
        "ao",
        "aos",
        "as",
        "com",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "e",
        "em",
        "na",
        "nas",
        "no",
        "nos",
        "o",
        "os",
        "para",
        "por",
        "que",
        "um",
        "uma",
    }
    words = [word for word in re.findall(r"[a-z0-9]+", normalized) if len(word) >= 3 and word not in stop_words]
    phrases = []
    if normalized and len(normalized) >= 4:
        phrases.append(normalized)
    phrases.extend(words)
    return _unique_terms(phrases)[:12]


def _unique_terms(terms: list[str]) -> list[str]:
    unique: list[str] = []
    for term in terms:
        clean = re.sub(r"\s+", " ", str(term)).strip()
        if clean and clean not in unique:
            unique.append(clean)
    return unique


def _suggestion_for_document_criterion(kind: str, name: str) -> str:
    if kind == "proibido":
        return f"Remover ou substituir o trecho associado ao criterio: {name}."
    return f"Incluir de forma clara o item esperado pelo criterio: {name}."


def analyze_os_pro(text: str, criteria: list[dict[str, Any]]) -> dict[str, Any]:
    original_text = text or ""
    normalized = normalize_text(original_text)
    total_weight = sum(float(item["peso"]) for item in criteria)
    earned = 0.0
    conformities: list[dict[str, Any]] = []
    nonconformities: list[dict[str, Any]] = []
    evidences: list[dict[str, Any]] = []
    has_forbidden_match = False

    for item in criteria:
        matches = _find_matches(original_text, normalized, item["termos"])
        is_forbidden = item["tipo"] == "proibido"
        if is_forbidden and matches:
            has_forbidden_match = True
        is_ok = not matches if is_forbidden else bool(matches)
        if is_ok:
            earned += float(item["peso"])
            conformities.append(
                {
                    "criterio": item["nome"],
                    "evidencia": matches[0].snippet if matches else "Nenhuma frase de risco encontrada.",
                }
            )
        else:
            nonconformities.append(
                {
                    "criterio": item["nome"],
                    "problema": matches[0].snippet if matches else "Nao localizado no atendimento.",
                    "sugestao": item.get("sugestao", ""),
                }
            )
        for match in matches:
            evidences.append({"criterio": item["nome"], "termo": match.term, "trecho": match.snippet})

    score = int(round((earned / total_weight) * 100)) if total_weight else 0
    if has_forbidden_match:
        score = min(score, ATTENTION_THRESHOLD + 14)
    status = _classify(score)
    return {
        "nota": score,
        "status": status,
        "conformidades": conformities,
        "nao_conformidades": nonconformities,
        "evidencias": evidences,
        "total_criterios": len(criteria),
        "criterios_conformes": len(conformities),
        "criterios_nao_conformes": len(nonconformities),
    }


def result_to_tables(result: dict[str, Any]) -> dict[str, pd.DataFrame]:
    return {
        "conformidades": pd.DataFrame(result.get("conformidades", [])),
        "nao_conformidades": pd.DataFrame(result.get("nao_conformidades", [])),
        "evidencias": pd.DataFrame(result.get("evidencias", [])),
    }


def analyze_with_ai(api_key: str, model: str, text: str, rule_result: dict[str, Any]) -> str:
    if not api_key.strip():
        return ""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Instale a dependencia 'openai' para ativar o modo IA.") from exc

    client = OpenAI(api_key=api_key.strip())
    requested_model = model.strip() or AUTO_MODEL
    fallback_models, available_models = _candidate_models(client, requested_model)
    compact_result = {
        "nota": rule_result.get("nota"),
        "status": rule_result.get("status"),
        "nao_conformidades": rule_result.get("nao_conformidades", []),
        "evidencias": rule_result.get("evidencias", [])[:12],
    }
    prompt = (
        "Voce e um auditor de qualidade de atendimento OS PRO. Analise o atendimento abaixo junto com "
        "o resultado das regras. Responda em portugues do Brasil, de forma objetiva, com as secoes: "
        "Leitura da IA, Riscos de reclamacao, Trecho mais problematico, Melhor resposta sugerida. "
        "Nao invente fatos que nao estejam no texto.\n\n"
        f"Resultado das regras:\n{json.dumps(compact_result, ensure_ascii=False, indent=2)}\n\n"
        f"Atendimento:\n{text[:12000]}"
    )
    errors: list[str] = []
    for candidate_model in fallback_models:
        try:
            response = client.responses.create(
                model=candidate_model,
                input=prompt,
                max_output_tokens=900,
            )
            output_text = getattr(response, "output_text", "")
            analysis = output_text.strip() if output_text else str(response)
            if candidate_model != requested_model:
                return (
                    f"Modelo solicitado sem acesso: {requested_model}. "
                    f"Analise gerada com fallback: {candidate_model}.\n\n{analysis}"
                )
            return analysis
        except Exception as exc:  # noqa: BLE001 - retry only for model access errors.
            if _is_model_access_error(exc):
                errors.append(f"{candidate_model}: {exc}")
                continue
            raise

    tried = ", ".join(fallback_models) if fallback_models else "nenhum modelo candidato"
    available_hint = (
        f" Modelos visiveis na chave: {', '.join(available_models[:20])}."
        if available_models
        else " Nao consegui listar modelos disponiveis para essa chave."
    )
    raise RuntimeError(
        "A chave API nao tem acesso aos modelos testados "
        f"({tried}). Altere o campo Modelo para um modelo liberado no seu projeto OpenAI."
        f"{available_hint}"
    )


def diagnose_openai_key(api_key: str) -> dict[str, Any]:
    if not api_key.strip():
        return {"ok": False, "message": "Informe uma chave API para testar.", "models": []}
    try:
        from openai import OpenAI
    except ImportError:
        return {"ok": False, "message": "Dependencia 'openai' nao instalada.", "models": []}

    client = OpenAI(api_key=api_key.strip())
    try:
        available_models = _list_available_models(client)
    except Exception as exc:  # noqa: BLE001 - diagnostic path should report the API error.
        return {
            "ok": False,
            "message": _friendly_openai_error(exc),
            "models": [],
        }

    text_models = _filter_text_model_ids(available_models)
    if text_models:
        return {
            "ok": True,
            "message": f"Chave valida. Modelos de texto encontrados: {', '.join(text_models[:10])}.",
            "models": text_models,
            "all_models": available_models,
        }
    return {
        "ok": False,
        "message": (
            "Chave valida, mas nenhum modelo de texto foi encontrado para este projeto. "
            "Confira Billing e Project > Limits > Model usage."
        ),
        "models": [],
        "all_models": available_models,
    }


def _candidate_models(client: Any, requested_model: str) -> tuple[list[str], list[str]]:
    try:
        available_models = _list_available_models(client)
    except Exception:  # noqa: BLE001 - listing is support only; model calls below are the real test.
        available_models = []
    model_is_auto = normalize_text(requested_model) in {AUTO_MODEL, "automatico", "detectar automaticamente"}
    requested_candidates = [] if model_is_auto else [requested_model]
    visible_text_models = _filter_text_model_ids(available_models)
    candidates = _unique_models([*requested_candidates, *PREFERRED_TEXT_MODELS, *visible_text_models])
    return candidates, available_models


def _list_available_models(client: Any) -> list[str]:
    models = client.models.list()
    ids = sorted(str(getattr(model, "id", "")).strip() for model in models.data)
    return [model_id for model_id in ids if model_id]


def _filter_text_model_ids(model_ids: list[str]) -> list[str]:
    candidates = []
    for model_id in model_ids:
        normalized = model_id.lower()
        if any(part in normalized for part in NON_TEXT_MODEL_PARTS):
            continue
        if normalized.startswith(("gpt-", "o1", "o3", "o4")) or normalized in {"chatgpt-4o-latest"}:
            candidates.append(model_id)
    return candidates


def _unique_models(models: list[str]) -> list[str]:
    unique: list[str] = []
    for model in models:
        clean = model.strip()
        if clean and clean not in unique:
            unique.append(clean)
    return unique


def _is_model_access_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "model_not_found" in text or "does not have access to model" in text or "model" in text and "not found" in text


def _friendly_openai_error(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "invalid_api_key" in lowered or "incorrect api key" in lowered or "401" in lowered:
        return "Chave invalida ou copiada incompleta. Gere uma nova chave e cole o valor completo que comeca com sk-."
    if "insufficient_quota" in lowered or "billing" in lowered or "quota" in lowered:
        return "A chave parece valida, mas a conta/projeto esta sem credito, sem billing ativo ou sem cota disponivel."
    if "permission" in lowered or "403" in lowered:
        return "A chave parece valida, mas o projeto nao tem permissao para o recurso/modelo solicitado."
    return f"Erro ao testar a chave: {text}"


def _read_pdf_text(file_bytes: bytes) -> str:
    extracted_texts = [_read_pdf_text_with_pypdf(file_bytes), _read_pdf_text_with_pymupdf(file_bytes)]
    text = "\n\n".join(item for item in extracted_texts if item.strip()).strip()
    if text:
        return text
    return _read_pdf_text_with_ocr(file_bytes)


def _read_pdf_text_with_pypdf(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    try:
        reader = PdfReader(BytesIO(file_bytes))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        return "\n\n".join(page for page in pages if page)
    except Exception:  # noqa: BLE001 - try the next PDF extractor.
        return ""


def _read_pdf_text_with_pymupdf(file_bytes: bytes) -> str:
    try:
        import fitz
    except ImportError:
        return ""

    try:
        pages = []
        with fitz.open(stream=file_bytes, filetype="pdf") as document:
            for page in document:
                pages.append((page.get_text("text") or "").strip())
        return "\n\n".join(page for page in pages if page)
    except Exception:  # noqa: BLE001 - OCR remains the final fallback.
        return ""


def _read_pdf_text_with_ocr(file_bytes: bytes) -> str:
    try:
        import fitz
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    try:
        pages = []
        with fitz.open(stream=file_bytes, filetype="pdf") as document:
            for page_index in range(min(document.page_count, 10)):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                pages.append(pytesseract.image_to_string(image, lang="por+eng").strip())
        return "\n\n".join(page for page in pages if page)
    except Exception:  # noqa: BLE001 - scanned PDF without local OCR support.
        return ""


def _find_matches(original_text: str, normalized_text: str, terms: list[str]) -> list[CriterionMatch]:
    matches: list[CriterionMatch] = []
    for term in terms:
        normalized_term = normalize_text(term)
        if not normalized_term or normalized_term not in normalized_text:
            continue
        snippet = _snippet_for_term(original_text, term, normalized_text, normalized_term)
        matches.append(CriterionMatch(term=term, snippet=snippet))
    return matches


def _snippet_for_term(original_text: str, term: str, normalized_text: str, normalized_term: str) -> str:
    direct = re.search(re.escape(term), original_text, flags=re.IGNORECASE)
    if direct:
        return _window(original_text, direct.start(), direct.end())

    approximate_index = normalized_text.find(normalized_term)
    if approximate_index < 0:
        return ""
    return _window(original_text, approximate_index, approximate_index + len(term))


def _window(text: str, start: int, end: int, radius: int = 110) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right].strip()
    snippet = re.sub(r"\s+", " ", snippet)
    if left > 0:
        snippet = "..." + snippet
    if right < len(text):
        snippet = snippet + "..."
    return snippet


def _classify(score: int) -> str:
    if score >= APPROVED_THRESHOLD:
        return "Aprovado"
    if score >= ATTENTION_THRESHOLD:
        return "Atencao"
    return "Reprovado"
