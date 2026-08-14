import base64
import json
import logging

import anthropic

from . import extractors
from .anonymize import anonymize_text, deanonymize_value

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def build_context_text(dgp, tz) -> str:
    lines = []
    for doc in (dgp, tz):
        lines.extend(doc.paragraphs)
        for table in doc.tables:
            for row in table:
                lines.append(" ".join(str(cell or "") for cell in row))
    return "\n".join(lines)


def _schema(missing_fields):
    return {
        "type": "object",
        "properties": {
            field: {"anyOf": [{"type": "string"}, {"type": "null"}]} for field in missing_fields
        },
        "required": missing_fields,
        "additionalProperties": False,
    }


def extract_missing_fields(missing_fields: list, context_text: str) -> dict:
    """Ask Claude for the passport fields regex and OCR couldn't find, over
    a depersonalized copy of the contract text.

    Never raises: a missing API key, no network, a timeout, an API error, or
    Natasha failing to load its model all just mean this call fills nothing,
    matching how ``ocr.recognize_text`` degrades on failure.
    """
    if not missing_fields:
        return {}

    try:
        anonymized_text, token_map = anonymize_text(context_text)
        response = _get_client().messages.create(
            model=MODEL,
            max_tokens=2048,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": _schema(missing_fields)},
            },
            messages=[{
                "role": "user",
                "content": (
                    "Найди в тексте ниже значения указанных полей паспорта "
                    "объекта недвижимости. Если поле в тексте отсутствует — "
                    "верни null, не придумывай значение.\n\n"
                    f"Поля: {', '.join(missing_fields)}\n\n{anonymized_text}"
                ),
            }],
        )
        raw_text = next(block.text for block in response.content if block.type == "text")
        raw = json.loads(raw_text)
    except Exception:
        logger.exception("AI extractor fallback failed")
        return {}

    if not isinstance(raw, dict):
        return {}

    # Deferred import: passport.py imports this module to wire in the
    # fallback, so importing passport at module level here would be circular.
    from . import passport as passport_module

    result = {}
    for field in missing_fields:
        value = raw.get(field)
        if value is None:
            continue
        value = deanonymize_value(value, token_map)
        if field in passport_module.NUMERIC_FIELDS:
            if isinstance(value, str):
                value = extractors.parse_number(value)
            if value is None:
                continue
        result[field] = value
    return result


CONTRACT_TERMS_IMAGE_FIELDS = ["smr_term", "advance_payment", "bank_guarantee", "performance_bond_pct"]


def _contract_terms_schema():
    return {
        "type": "object",
        "properties": {
            field: {"anyOf": [{"type": "string"}, {"type": "null"}]}
            for field in CONTRACT_TERMS_IMAGE_FIELDS
        },
        "required": CONTRACT_TERMS_IMAGE_FIELDS,
        "additionalProperties": False,
    }


def extract_contract_terms_from_images(images: list) -> dict:
    """Ask Claude to read a scanned contract-terms protocol directly as an
    image and return the fields ``build_contract_terms`` needs.

    Used only when the source PDF has no text layer at all — a genuine scan
    — where local OCR would take minutes on this CPU-only setup. There's no
    text-based anonymization equivalent for an image, so the page (with any
    real company names or signatures on it) goes to the API unredacted, by
    explicit choice for this document type. Never raises: any failure — no
    API key, no network, a bad response — just means nothing gets filled,
    same as ``extract_missing_fields``.
    """
    if not images:
        return {}

    try:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(image).decode("ascii"),
                },
            }
            for image in images
        ]
        content.append({
            "type": "text",
            "text": (
                "Это скан протокола окончательных условий по договору. Найди на "
                "изображении значения полей:\n"
                "- smr_term: срок выполнения СМР (строительно-монтажных работ)\n"
                "- advance_payment: условия по авансу, %\n"
                "- bank_guarantee: включена ли банковская гарантия на возврат "
                "аванса — ответь строго \"Включено\" или \"Не включено\"\n"
                "- performance_bond_pct: performance bond, %\n\n"
                "Если поле не найдено на изображении — верни null, не придумывай значение."
            ),
        })
        response = _get_client().messages.create(
            model=MODEL,
            max_tokens=1024,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": _contract_terms_schema()},
            },
            messages=[{"role": "user", "content": content}],
        )
        raw_text = next(block.text for block in response.content if block.type == "text")
        raw = json.loads(raw_text)
    except Exception:
        logger.exception("Contract terms image extractor failed")
        return {}

    if not isinstance(raw, dict):
        return {}
    return {
        field: raw.get(field) for field in CONTRACT_TERMS_IMAGE_FIELDS if raw.get(field) is not None
    }
