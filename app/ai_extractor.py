import json

import anthropic

from . import extractors
from .anonymize import anonymize_text, deanonymize_value

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
        "properties": {field: {"type": ["string", "null"]} for field in missing_fields},
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
            thinking={"type": "disabled"},
            output_config={
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
