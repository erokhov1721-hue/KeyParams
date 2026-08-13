# AI Search Fallback (Claude API + Natasha Anonymization) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When regex extraction and the OCR fallback both leave a passport field empty, depersonalize the contract text (Natasha NER: organizations/persons/ИНН → tokens) and ask Claude API for just the missing fields, then substitute real values back in and mark those fields as AI-filled.

**Architecture:** Two new standalone modules — `app/anonymize.py` (Natasha-based tokenization, no Claude dependency) and `app/ai_extractor.py` (builds the flat context text, calls Claude with a JSON-schema structured output, de-anonymizes the result, numeric-parses area/price fields). `app/passport.py`'s `build_passport` calls the new fallback after the existing OCR fallback, exactly mirroring how `ocr_fields` already works today, and a new `ai_fields` list is added to the passport JSON. `app/routes.py` and `app/templates/project.html` get the same "found via X, clear the flag on manual edit" treatment already in place for `ocr_fields`.

**Tech Stack:** Python 3, Flask, `anthropic` SDK (`client.messages.create` with `output_config.format` structured output, model `claude-opus-5`), `natasha` (NER for Russian).

## Global Constraints

- Depersonalization is **never optional** — there is no environment variable or config flag to disable it. Every call to Claude in this feature goes through `anonymize_text` first.
- The Claude fallback step itself has **no on/off environment variable** either (unlike `OCR_FALLBACK_ENABLED`) — it is always available, but only actually calls the API when there are still-missing fields after regex + OCR.
- Any failure at the Claude step (missing `ANTHROPIC_API_KEY`, no network, timeout, API error, Natasha failing to load its model) must **never** raise out of `build_passport` — it just means the fallback fills nothing for the affected fields, exactly like the existing OCR fallback's failure behavior in `app/ocr.py::recognize_text`.
- Model ID is exactly `claude-opus-5` (the current Claude Opus alias) — never a dated/suffixed variant.
- Numeric fields (`app/passport.py::NUMERIC_FIELDS` = the three area fields + `contract_price_rub`) must be run through `app/extractors.py::parse_number` after de-anonymization, same as every other extraction path in this app.
- New dependencies (`anthropic`, `natasha`) go in `requirements.txt`, unpinned-minor like the existing entries (e.g. `openpyxl>=3.1,<4.0` style).

---

### Task 1: Depersonalization module (`app/anonymize.py`)

**Files:**
- Create: `app/anonymize.py`
- Modify: `requirements.txt`
- Test: `tests/test_anonymize.py`

**Interfaces:**
- Produces: `anonymize_text(text: str) -> tuple[str, dict[str, str]]` — returns `(anonymized_text, token_map)` where `token_map` maps each token (e.g. `"<ORGANIZATION_1>"`) back to the original substring it replaced.
- Produces: `deanonymize_value(value, token_map: dict) -> value` — if `value` is a string that exactly equals a key in `token_map`, returns the mapped original; otherwise returns `value` unchanged (including non-string values, passed through as-is).

- [ ] **Step 1: Add dependencies**

Add these two lines to `requirements.txt` (after the existing `reportlab` line):

```
anthropic>=0.70,<1.0
natasha>=1.6,<2.0
```

- [ ] **Step 2: Install the new dependencies**

Run: `pip install -r requirements.txt`

Expected: `anthropic` and `natasha` install successfully (natasha pulls in `navec`, `slovnet`, `razdel`, `pymorphy2`-adjacent packages as its own dependencies — that's expected).

- [ ] **Step 3: Write the failing tests**

Create `tests/test_anonymize.py`:

```python
from app.anonymize import anonymize_text, deanonymize_value


def test_anonymize_text_replaces_organization_name():
    text = 'Договор заключён с ООО «Ромашка», далее именуемым Генподрядчик.'
    anonymized, token_map = anonymize_text(text)
    assert "Ромашка" not in anonymized
    assert any("Ромашка" in original for original in token_map.values())


def test_anonymize_text_replaces_person_name():
    text = 'Договор подписан со стороны Заказчика Ивановым Иваном Ивановичем.'
    anonymized, token_map = anonymize_text(text)
    assert "Ивановым Иваном Ивановичем" not in anonymized
    assert any("Иван" in original for original in token_map.values())


def test_anonymize_text_replaces_inn_10_digits():
    text = 'Генподрядчик ООО «Ромашка», ИНН 7701234567.'
    anonymized, token_map = anonymize_text(text)
    assert "7701234567" not in anonymized
    assert any(value == "7701234567" for value in token_map.values())


def test_anonymize_text_replaces_inn_12_digits():
    text = 'ИП Петров П.П., ИНН 771234567890, выступает субподрядчиком.'
    anonymized, token_map = anonymize_text(text)
    assert "771234567890" not in anonymized
    assert any(value == "771234567890" for value in token_map.values())


def test_anonymize_text_reuses_token_for_repeated_mention():
    text = 'ООО «Ромашка» подписывает договор. Далее ООО «Ромашка» обязуется выполнить работы.'
    anonymized, token_map = anonymize_text(text)
    org_tokens = [t for t in token_map if t.startswith("<ORGANIZATION_")]
    assert len(org_tokens) == 1
    assert anonymized.count(org_tokens[0]) == 2


def test_anonymize_text_numbers_inn_tokens_in_order_of_first_mention():
    text = (
        'Первый субподрядчик, ИНН 7701234567, указан здесь. '
        'Второй субподрядчик, ИНН 7809876543, указан позже.'
    )
    _, token_map = anonymize_text(text)
    assert token_map["<INN_1>"] == "7701234567"
    assert token_map["<INN_2>"] == "7809876543"


def test_deanonymize_value_restores_original():
    token_map = {"<ORGANIZATION_1>": 'ООО «Ромашка»'}
    assert deanonymize_value("<ORGANIZATION_1>", token_map) == 'ООО «Ромашка»'


def test_deanonymize_value_passes_through_unknown_string():
    assert deanonymize_value("Бизнес", {}) == "Бизнес"


def test_deanonymize_value_passes_through_non_string():
    assert deanonymize_value(2025, {}) == 2025
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/test_anonymize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.anonymize'` (or import error), since the module doesn't exist yet.

- [ ] **Step 5: Implement `app/anonymize.py`**

```python
import re

from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter

# 10 or 12 digits right after "ИНН" (with or without a separator), not
# followed by another digit — so a 12-digit ИНН isn't cut short by the
# 10-digit alternative matching just its first 10 digits.
_INN_RE = re.compile(r'ИНН[:\s]*(\d{12}|\d{10})(?!\d)', re.IGNORECASE)

_TYPE_PREFIX = {"PER": "PERSON", "ORG": "ORGANIZATION"}

_segmenter = None
_ner_tagger = None


def _get_natasha():
    global _segmenter, _ner_tagger
    if _segmenter is None:
        embedding = NewsEmbedding()
        _segmenter = Segmenter()
        _ner_tagger = NewsNERTagger(embedding)
    return _segmenter, _ner_tagger


def anonymize_text(text: str):
    """Replace every organization, person, and ИНН mention in ``text`` with
    a token — ``<ORGANIZATION_N>``, ``<PERSON_N>``, ``<INN_N>`` — numbered
    within its own category in the order it's first mentioned. The same
    mention (matched case-insensitively) always gets the same token.

    Returns ``(anonymized_text, token_map)`` where ``token_map`` maps each
    token back to the original substring it replaced.
    """
    segmenter, ner_tagger = _get_natasha()
    doc = Doc(text)
    doc.segment(segmenter)
    doc.tag_ner(ner_tagger)

    spans = []
    for span in doc.spans:
        prefix = _TYPE_PREFIX.get(span.type)
        if prefix is None:
            continue
        spans.append((span.start, span.stop, prefix, span.text))
    for match in _INN_RE.finditer(text):
        spans.append((match.start(1), match.end(1), "INN", match.group(1)))
    spans.sort(key=lambda s: s[0])

    token_map = {}
    token_by_mention = {}
    counters = {"PERSON": 0, "ORGANIZATION": 0, "INN": 0}
    pieces = []
    cursor = 0
    for start, stop, prefix, original in spans:
        if start < cursor:
            continue  # overlaps a span already emitted — skip rather than double-count
        key = (prefix, original.lower())
        token = token_by_mention.get(key)
        if token is None:
            counters[prefix] += 1
            token = f"<{prefix}_{counters[prefix]}>"
            token_by_mention[key] = token
            token_map[token] = original
        pieces.append(text[cursor:start])
        pieces.append(token)
        cursor = stop
    pieces.append(text[cursor:])
    return "".join(pieces), token_map


def deanonymize_value(value, token_map: dict):
    """If ``value`` is a string that exactly matches a token, return the
    original text it stood for; otherwise return ``value`` unchanged."""
    if isinstance(value, str) and value in token_map:
        return token_map[value]
    return value
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_anonymize.py -v`
Expected: PASS — all 9 tests green. The first run downloads Natasha's embedding model (needs network; this environment already has `pip-system-certs` installed for exactly this kind of corporate-SSL-interception issue, per the EasyOCR precedent).

**If `test_anonymize_text_replaces_organization_name` or `test_anonymize_text_replaces_person_name` fail:** Natasha's NER tagger is a real trained model and might tag the example text differently than expected. Add `print(list(doc.spans))` temporarily in a throwaway script to see exactly what `doc.spans` contains for the test's input text, then adjust the test's input sentence (not the implementation) to a phrasing Natasha reliably tags — the assertions themselves (substring absent from anonymized text, present in `token_map.values()`) are already tolerant of exact span boundaries and don't need to change.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt app/anonymize.py tests/test_anonymize.py
git commit -m "feat: add NER-based text anonymization for the AI search fallback"
```

---

### Task 2: Claude API extraction module (`app/ai_extractor.py`)

**Files:**
- Create: `app/ai_extractor.py`
- Test: `tests/test_ai_extractor.py`

**Interfaces:**
- Consumes: `app.anonymize.anonymize_text`, `app.anonymize.deanonymize_value` (Task 1). `app.extractors.parse_number` (existing). `app.passport.NUMERIC_FIELDS` (existing constant, `("underground_area_sqm", "aboveground_area_sqm", "total_area_sqm", "contract_price_rub")`) — imported **inside the function body**, not at module level (see Step 2 comment for why).
- Consumes: `app.document_reader.DocxContent` (existing dataclass with `.paragraphs` and `.tables`).
- Produces: `build_context_text(dgp, tz) -> str` — flattens both documents' paragraphs and table rows into one newline-joined text blob.
- Produces: `extract_missing_fields(missing_fields: list, context_text: str) -> dict` — returns `{field: value}` only for fields Claude actually found (never includes a field mapped to `None`). Never raises.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ai_extractor.py`:

```python
import json

from app import ai_extractor
from app.document_reader import DocxContent


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, content_text):
        self.content = [_FakeTextBlock(content_text)]


class _FakeMessages:
    def __init__(self, response_text):
        self.response_text = response_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeMessage(self.response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


class _RaisingClient:
    class messages:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("no network")


def test_build_context_text_combines_paragraphs_and_tables_from_both_docs():
    dgp = DocxContent(paragraphs=["Пункт 1 ДГП"], tables=[[["Генподрядчик", "ООО «Ромашка»"]]])
    tz = DocxContent(paragraphs=["Пункт 1 ТЗ"], tables=[[["Площадь", "67413"]]])

    text = ai_extractor.build_context_text(dgp, tz)

    assert "Пункт 1 ДГП" in text
    assert "Генподрядчик ООО «Ромашка»" in text
    assert "Пункт 1 ТЗ" in text
    assert "Площадь 67413" in text


def test_extract_missing_fields_sends_anonymized_text_not_real_names(monkeypatch):
    fake_client = _FakeClient(json.dumps({"general_contractor": "<ORGANIZATION_1>"}))
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: fake_client)

    context = 'Генподрядчик ООО «Ромашка», ИНН 7701234567, выполняет работы.'
    result = ai_extractor.extract_missing_fields(["general_contractor"], context)

    sent_text = fake_client.messages.calls[0]["messages"][0]["content"]
    assert "Ромашка" not in sent_text
    assert "7701234567" not in sent_text
    assert result["general_contractor"] == 'ООО «Ромашка»'


def test_extract_missing_fields_returns_only_non_null_fields(monkeypatch):
    fake_client = _FakeClient(json.dumps({
        "general_contractor": None, "year_signed": "2024",
    }))
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: fake_client)

    result = ai_extractor.extract_missing_fields(
        ["general_contractor", "year_signed"], "какой-то текст без реальных имён",
    )

    assert result == {"year_signed": "2024"}


def test_extract_missing_fields_parses_numeric_field_through_parse_number(monkeypatch):
    fake_client = _FakeClient(json.dumps({"total_area_sqm": "67 413,00"}))
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: fake_client)

    result = ai_extractor.extract_missing_fields(["total_area_sqm"], "текст")

    assert result == {"total_area_sqm": 67413.0}


def test_extract_missing_fields_empty_list_returns_empty_without_calling_client(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: calls.append(1))

    result = ai_extractor.extract_missing_fields([], "текст")

    assert result == {}
    assert calls == []


def test_extract_missing_fields_client_error_returns_empty_dict(monkeypatch):
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: _RaisingClient())

    result = ai_extractor.extract_missing_fields(["general_contractor"], "текст")

    assert result == {}


def test_extract_missing_fields_malformed_json_returns_empty_dict(monkeypatch):
    fake_client = _FakeClient("not valid json")
    monkeypatch.setattr(ai_extractor, "_get_client", lambda: fake_client)

    result = ai_extractor.extract_missing_fields(["general_contractor"], "текст")

    assert result == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_ai_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai_extractor'`.

- [ ] **Step 3: Implement `app/ai_extractor.py`**

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_ai_extractor.py -v`
Expected: PASS — all 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add app/ai_extractor.py tests/test_ai_extractor.py
git commit -m "feat: add Claude API extraction for still-missing passport fields"
```

---

### Task 3: Wire the fallback into `build_passport` (`app/passport.py`)

**Files:**
- Modify: `app/passport.py:1-119` (imports, `_apply_ocr_fallback`, `build_passport`)
- Test: `tests/test_passport.py`

**Interfaces:**
- Consumes: `app.ai_extractor.build_context_text`, `app.ai_extractor.extract_missing_fields` (Task 2).
- Produces: `build_passport(...)`'s returned dict now also has an `"ai_fields"` key — a list of field names Claude filled in, exactly parallel to the existing `"ocr_fields"` key.

**Why `_apply_ocr_fallback`'s return value changes:** per the spec, the AI fallback's context text must include any OCR-recognized text from step 2, so `build_passport` needs access to the OCR'd `DocxContent` for both documents even when it's empty (OCR fallback disabled, or not needed). Today `_apply_ocr_fallback` only returns the list of filled field names; three early-return points would each need to independently construct empty `DocxContent` objects if callers reached in and rebuilt them separately, so the cleanest fix is to have `_apply_ocr_fallback` return them directly as part of its result.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_passport.py` (near the existing OCR fallback tests, after `test_build_passport_ocr_skips_tz_when_only_dgp_field_missing`):

```python
from app import ai_extractor


def test_build_passport_ai_fallback_fills_missing_field(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ai_extractor, "extract_missing_fields",
        lambda missing_fields, context_text: {"general_contractor": "ООО «Тест»"},
    )
    dgp_xml = document_xml()  # no general_contractor phrase anywhere
    tz_xml = document_xml(tables=[[["Общая площадь", "67413", "м2"]]])
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["general_contractor"] == "ООО «Тест»"
    assert result["ai_fields"] == ["general_contractor"]


def test_build_passport_ai_fallback_skipped_when_nothing_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ai_extractor, "extract_missing_fields",
        lambda missing_fields, context_text: calls.append(missing_fields) or {},
    )
    dgp_xml = document_xml(paragraphs=[
        "г. Москва",
        "«04» февраля 2025 г.",
        "Жилой комплекс бизнес-класса.",
        "Цена Работ по настоящему Договору составляет 10 067 050 887,72 руб., включая НДС.",
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,",
    ])
    tz_xml = document_xml(tables=[[
        ["1", "Площадь подземной части", "м2", "1 000"],
        ["2", "Площадь надземной части", "м2", "2 000"],
        ["3", "Общая площадь", "м2", "3 000"],
    ]])
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["ai_fields"] == []
    assert calls == []


def test_build_passport_ai_fallback_failure_leaves_fields_none(tmp_path, monkeypatch):
    # Mirrors how the OCR fallback degrades on failure: extract_missing_fields
    # is contracted to never raise, returning {} on any internal error, so
    # build_passport just sees "nothing found" and keeps going.
    monkeypatch.setattr(
        ai_extractor, "extract_missing_fields",
        lambda missing_fields, context_text: {},
    )
    dgp_xml = document_xml()
    tz_xml = document_xml()
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["ai_fields"] == []
    assert result["total_area_sqm"] is None


def test_build_passport_ai_context_includes_ocr_text_when_ocr_ran(tmp_path, monkeypatch):
    monkeypatch.setenv(passport.OCR_FALLBACK_ENV_VAR, "1")
    monkeypatch.setattr(
        ocr, "recognize_text",
        lambda images: ["Генподрядчик ООО «Из Картинки»"] * len(images),
    )
    captured = {}

    def fake_extract(missing_fields, context_text):
        captured["context_text"] = context_text
        return {}

    monkeypatch.setattr(ai_extractor, "extract_missing_fields", fake_extract)

    dgp_xml = document_xml()
    tz_xml = document_xml()
    dgp_path = make_docx(
        tmp_path, dgp_xml, "dgp.docx",
        extra_files={"word/media/image1.png": b"fake-image-bytes"},
    )
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    passport.build_passport("Тест", dgp_path, tz_path)

    assert "Из Картинки" in captured["context_text"]
```

Also update the import line at the top of `tests/test_passport.py` (currently `from app import ocr, passport`) to:

```python
from app import ai_extractor, ocr, passport
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_passport.py -v`
Expected: FAIL on the four new tests — `KeyError: 'ai_fields'` (the key doesn't exist yet) or `AttributeError: module 'app.ai_extractor' has no attribute ...` if the import itself fails first.

- [ ] **Step 3: Modify `app/passport.py`**

Change the import line (currently line 5):

```python
# Before
from . import extractors, ocr

# After
from . import ai_extractor, extractors, ocr
```

Replace `_apply_ocr_fallback` (currently lines 57-103) with:

```python
def _apply_ocr_fallback(data, dgp, tz):
    empty_ocr = DocxContent(paragraphs=[], tables=[])
    if os.environ.get(OCR_FALLBACK_ENV_VAR) != "1":
        return [], empty_ocr, empty_ocr

    missing = [f for f in PASSPORT_FIELDS if f != "project_name" and data[f] is None]
    if not missing:
        return [], empty_ocr, empty_ocr

    needs_dgp_ocr = any(f in TEXT_FIELDS for f in missing)
    needs_tz_ocr = any(f == "building_class" or f in AREA_FIELDS for f in missing)

    dgp_lines = _ocr_lines(dgp.images) if needs_dgp_ocr else []
    tz_lines = _ocr_lines(tz.images) if needs_tz_ocr else []

    ocr_dgp = DocxContent(paragraphs=dgp_lines, tables=[])
    ocr_tz = DocxContent(paragraphs=tz_lines, tables=[])

    filled = []
    if data["general_contractor"] is None:
        value = extractors.extract_general_contractor(ocr_dgp)
        if value is not None:
            data["general_contractor"] = value
            filled.append("general_contractor")
    if data["contract_price_rub"] is None:
        value = extractors.extract_contract_price(ocr_dgp)
        if value is not None:
            data["contract_price_rub"] = value
            filled.append("contract_price_rub")
    if data["year_signed"] is None:
        value = extractors.extract_signing_year(ocr_dgp)
        if value is not None:
            data["year_signed"] = value
            filled.append("year_signed")
    if data["building_class"] is None:
        value = extractors.extract_building_class(ocr_dgp, ocr_tz)
        if value is not None:
            data["building_class"] = value
            filled.append("building_class")
    for field in AREA_FIELDS:
        if data[field] is not None:
            continue
        must_contain, must_not_contain = AREA_TOKENS[field]
        value = extractors._find_area_value_in_text(tz_lines, must_contain, must_not_contain)
        if value is not None:
            data[field] = value
            filled.append(field)
    return filled, ocr_dgp, ocr_tz
```

(Only the top guard clauses and the final `return` line changed — the body between them is untouched.)

Replace `build_passport` (currently lines 106-120) with:

```python
def build_passport(project_name: str, dgp_path, tz_path) -> dict:
    dgp = read_docx(dgp_path)
    tz = read_docx(tz_path)
    data = {
        "project_name": project_name,
        "year_signed": extractors.extract_signing_year(dgp),
        "building_class": extractors.extract_building_class(dgp, tz),
        "general_contractor": extractors.extract_general_contractor(dgp),
        "contract_price_rub": extractors.extract_contract_price(dgp),
        "underground_area_sqm": extractors.extract_underground_area(tz),
        "aboveground_area_sqm": extractors.extract_aboveground_area(tz),
        "total_area_sqm": extractors.extract_total_area(tz),
    }
    data["ocr_fields"], ocr_dgp, ocr_tz = _apply_ocr_fallback(data, dgp, tz)
    data["ai_fields"] = _apply_ai_fallback(data, dgp, tz, ocr_dgp, ocr_tz)
    return data


def _apply_ai_fallback(data, dgp, tz, ocr_dgp, ocr_tz):
    missing = [f for f in PASSPORT_FIELDS if f != "project_name" and data[f] is None]
    if not missing:
        return []

    context_text = ai_extractor.build_context_text(dgp, tz)
    ocr_text = "\n".join(ocr_dgp.paragraphs + ocr_tz.paragraphs)
    if ocr_text:
        context_text = context_text + "\n" + ocr_text

    found = ai_extractor.extract_missing_fields(missing, context_text)
    for field, value in found.items():
        data[field] = value
    return list(found.keys())
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_passport.py -v`
Expected: PASS — all tests green, including the pre-existing OCR fallback tests (their assertions on `result["ocr_fields"]` are unaffected by the return-tuple change since `build_passport` unpacks it internally).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: PASS (same count as before this task, plus the 4 new tests).

- [ ] **Step 6: Commit**

```bash
git add app/passport.py tests/test_passport.py
git commit -m "feat: wire the Claude API fallback into build_passport"
```

---

### Task 4: Surface `ai_fields` in the UI (`app/routes.py`, `app/templates/project.html`, `app/static/style.css`)

**Files:**
- Modify: `app/routes.py:166-178` (`project_page`), `app/routes.py:218-244` (`update_project`)
- Modify: `app/templates/project.html:1-45`
- Modify: `app/static/style.css:1-15`, `app/static/style.css:499-530`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `data["ai_fields"]` from a loaded passport (Task 3).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_routes.py` (near the existing `ocr_fields` badge tests — look for the test around line 462 that asserts `"С картинки".encode("utf-8") in resp.data`):

```python
def test_project_page_shows_ai_badge_for_ai_filled_field(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    from app import storage, passport as passport_module

    slug = storage.create_project(tmp_path, "Проект с AI-полем")
    passport_module.save_passport({
        "project_name": "Проект с AI-полем",
        "year_signed": None,
        "building_class": None,
        "general_contractor": "ООО «Из AI»",
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": None,
        "ocr_fields": [],
        "ai_fields": ["general_contractor"],
    }, storage.passport_path(tmp_path, slug))

    resp = client.get(f"/projects/{slug}")

    assert resp.status_code == 200
    assert "Найдено через AI".encode("utf-8") in resp.data


def test_update_project_clears_ai_flag_when_value_changes(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    from app import storage, passport as passport_module

    slug = storage.create_project(tmp_path, "Проект с AI-полем")
    path = storage.passport_path(tmp_path, slug)
    passport_module.save_passport({
        "project_name": "Проект с AI-полем",
        "year_signed": None,
        "building_class": None,
        "general_contractor": None,
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": 67413.0,
        "ocr_fields": [],
        "ai_fields": ["total_area_sqm"],
    }, path)

    client.post(f"\\projects\\{slug}", data={"total_area_sqm": "70000"})

    saved = passport_module.load_passport(path)
    assert saved["total_area_sqm"] == 70000.0
    assert saved["ai_fields"] == []


def test_update_project_keeps_ai_flag_when_value_unchanged(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    from app import storage, passport as passport_module

    slug = storage.create_project(tmp_path, "Проект с AI-полем")
    path = storage.passport_path(tmp_path, slug)
    passport_module.save_passport({
        "project_name": "Проект с AI-полем",
        "year_signed": None,
        "building_class": None,
        "general_contractor": None,
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": 67413.0,
        "ocr_fields": [],
        "ai_fields": ["total_area_sqm"],
    }, path)

    client.post(f"\\projects\\{slug}", data={"total_area_sqm": "67413"})

    saved = passport_module.load_passport(path)
    assert saved["ai_fields"] == ["total_area_sqm"]
```

(These mirror the file's existing `_...ocr..._` tests — check the top of `tests/test_routes.py` for its `create_app` import and reuse it exactly as the neighboring tests do.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_routes.py -v`
Expected: FAIL — `test_project_page_shows_ai_badge_for_ai_filled_field` fails because the template never renders "Найдено через AI"; the two `update_project` tests fail because `ai_fields` isn't in the saved JSON (`load_passport` won't have added it, and `KeyError`/`assert None == []`-style failures should appear, or the key is simply absent and the assertion fails).

- [ ] **Step 3: Modify `app/routes.py`**

In `project_page` (around line 166), add `ai_fields` to the `render_template` call:

```python
    return render_template(
        "project.html",
        slug=slug,
        passport=data,
        fields=passport_module.PASSPORT_FIELDS,
        field_labels=passport_module.FIELD_LABELS,
        ocr_fields=data.get("ocr_fields", []),
        ai_fields=data.get("ai_fields", []),
        price_per_sqm=passport_module.price_per_sqm(data),
        building_class_options=passport_module.BUILDING_CLASS_OPTIONS,
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        has_estimate=storage.estimate_path(root, slug).exists(),
    )
```

In `update_project` (around line 219), track and clear `ai_fields` the same way `ocr_fields` already is:

```python
@bp.route("/projects/<slug>", methods=["POST"])
def update_project(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)
    data = passport_module.load_passport(path)
    ocr_fields = list(data.get("ocr_fields", []))
    ai_fields = list(data.get("ai_fields", []))
    for field in passport_module.PASSPORT_FIELDS:
        if field == "project_name":
            continue
        old_value = data.get(field)
        raw_value = request.form.get(field, "").strip()
        if not raw_value:
            new_value = None
        elif field in passport_module.NUMERIC_FIELDS:
            new_value = extractors.parse_number(raw_value)
        else:
            new_value = raw_value
        data[field] = new_value
        if new_value != old_value and field in ocr_fields:
            ocr_fields.remove(field)
        if new_value != old_value and field in ai_fields:
            ai_fields.remove(field)
    data["ocr_fields"] = ocr_fields
    data["ai_fields"] = ai_fields
    passport_module.save_passport(data, path)
    return redirect(url_for("main.project_page", slug=slug))
```

- [ ] **Step 4: Modify `app/templates/project.html`**

Update the hint paragraph (currently lines 7-9):

```html
    <p class="page-sub">
      Синий — распознано с картинки, стоит проверить.
      Фиолетовый — найдено через AI, стоит проверить.
      Жёлтый — заполните вручную.
    </p>
```

Update the field-row block (currently lines 22-30):

```html
      {% set value = passport[field] %}
      {% set is_ocr = field in ocr_fields %}
      {% set is_ai = field in ai_fields %}
      <div class="field-row {{ 'is-empty' if value is none else ('is-ocr' if is_ocr else ('is-ai' if is_ai else 'is-filled')) }}">
        <div class="field-label-col">
          <span class="field-label">{{ field_labels.get(field, field) }}</span>
          {% if is_ocr %}
            <span class="badge badge-ocr">С картинки — проверьте</span>
          {% elif is_ai %}
            <span class="badge badge-ai">Найдено через AI — проверьте</span>
          {% endif %}
        </div>
```

- [ ] **Step 5: Modify `app/static/style.css`**

Add a purple color pair to the `:root` block (currently lines 1-15), after the `--blue-100` line:

```css
  --purple-600: #6d4aab;
  --purple-100: #ece5f7;
```

Add badge and field-row styling after the existing `.field-row.is-ocr` rule (currently lines 526-530):

```css
.badge-ai {
  background: var(--purple-100);
  color: var(--purple-600);
}

.field-row.is-ai input[type="text"],
.field-row.is-ai select {
  border-color: #cabbe6;
  background: var(--purple-100);
}
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_routes.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest`
Expected: PASS — full green suite, same total as before this task plus the 3 new tests.

- [ ] **Step 8: Manual smoke test**

Start the app (`flask --app app run` or however it's normally started in this project — check `README`/existing run instructions), open a project whose passport JSON has been hand-edited to include `"ai_fields": ["general_contractor"]` for a filled field, and visually confirm the purple badge and input border render correctly, and that saving the form after changing that field's value clears the badge on reload (matching the automated test's assertion visually).

- [ ] **Step 9: Commit**

```bash
git add app/routes.py app/templates/project.html app/static/style.css tests/test_routes.py
git commit -m "feat: show a distinct badge for fields filled via the AI fallback"
```

---

## Self-Review Notes

**Spec coverage:**
- Общий поток (regex → OCR → Claude, Claude only called when fields remain missing, no env-var toggle for the Claude step) — Task 3.
- Деперсонализация (`app/anonymize.py`, PER/ORG/ИНН tokens, `anonymize_text`/`deanonymize_value`) — Task 1.
- Запрос к Claude (`app/ai_extractor.py`, `build_context_text`, `extract_missing_fields`, JSON schema, `claude-opus-5`, `ANTHROPIC_API_KEY` from environment via the SDK's default client) — Task 2.
- Обработка ошибок (never interrupts passport creation) — Task 2 (`extract_missing_fields` never raises) + Task 3 (`build_passport` doesn't need its own guard, matching the OCR precedent).
- Интеграция в `build_passport`, `data["ai_fields"]` — Task 3.
- Интерфейс (badge, clears on manual edit) — Task 4.
- Зависимости (`anthropic`, `natasha` in `requirements.txt`) — Task 1.
- Тесты for all three modules — Tasks 1, 2, 3.

**Placeholder scan:** none found — every step has real code, real assertions, and concrete file/line references.

**Type consistency:** `anonymize_text` / `deanonymize_value` signatures match between Task 1's implementation and Task 2's usage. `build_context_text` / `extract_missing_fields` signatures match between Task 2's implementation and Task 3's usage. `ai_fields` key name is consistent across Tasks 3 and 4.
