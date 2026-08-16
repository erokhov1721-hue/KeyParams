import json
import os
import re
from pathlib import Path

from . import (
    ai_extractor, contract_extractors, extractors, ocr, ocr_lines, pdf_reader,
    protocol_columns, win_ocr,
)
from .document_reader import DocxContent, read_docx

# The EasyOCR fallback is CPU-only in this environment and can take several
# minutes per project, so it stays opt-in: set OCR_FALLBACK_ENABLED=1 in the
# environment before starting the app to turn it back on. The Windows engine
# needs no such protection — it reads a whole technical specification's worth
# of pictures in under two seconds — so where it exists, it simply runs.
OCR_FALLBACK_ENV_VAR = "OCR_FALLBACK_ENABLED"

PASSPORT_FIELDS = [
    "project_name", "address", "year_signed", "building_class",
    "general_contractor", "contract_price_rub", "underground_area_sqm",
    "aboveground_area_sqm", "total_area_sqm",
]

FIELD_LABELS = {
    "project_name": "Название проекта",
    "address": "Адрес объекта",
    "year_signed": "Год подписания договора",
    "building_class": "Класс здания",
    "general_contractor": "Генподрядчик",
    "contract_price_rub": "Цена работ, руб.",
    "underground_area_sqm": "Площадь подземной части, м²",
    "aboveground_area_sqm": "Площадь надземной части, м²",
    "total_area_sqm": "Общая площадь комплекса, м²",
}

TEXT_FIELDS = (
    "address", "year_signed", "building_class", "general_contractor", "contract_price_rub",
)
AREA_FIELDS = ("underground_area_sqm", "aboveground_area_sqm", "total_area_sqm")
NUMERIC_FIELDS = AREA_FIELDS + ("contract_price_rub",)

BUILDING_CLASS_OPTIONS = ["Эконом", "Комфорт", "Бизнес", "Бизнес - Премиум", "Премиум", "Элит"]

# The "Паспорт договора" card — filled from a separately uploaded contract
# terms protocol (often a PDF), independent of the object passport above.
CONTRACT_FIELDS = ["smr_term", "advance_payment", "bank_guarantee", "performance_bond_pct", "vat"]

CONTRACT_FIELD_LABELS = {
    "smr_term": "Срок СМР",
    "advance_payment": "Аванс",
    "bank_guarantee": "Банковская гарантия",
    "performance_bond_pct": "Performance bond, %",
    "vat": "НДС",
}

AREA_TOKENS = {
    "underground_area_sqm": (('площад', 'подземн'), extractors.FOOTPRINT_EXCLUSION),
    "aboveground_area_sqm": (
        ('площад', ('надземн', 'наземн')), extractors.FOOTPRINT_EXCLUSION,
    ),
    "total_area_sqm": (
        ('обща', 'площад'),
        ('подземн', 'надземн', 'наземн') + extractors.FOOTPRINT_EXCLUSION,
    ),
}


def _ocr_lines(engine, images):
    if not images:
        return []
    lines = []
    for text in engine.recognize_text(images):
        lines.extend(text.splitlines())
    return lines


def _passport_ocr_engine():
    """Which engine reads the pictures inside the documents, if any.

    Windows' own engine is fast enough that there is nothing to protect the
    user from, so it runs whenever it's there. EasyOCR is not, and keeps the
    opt-in it has always had: a project that would have taken a second now
    taking several minutes is not something to spring on someone.
    """
    if win_ocr.available():
        return win_ocr
    if os.environ.get(OCR_FALLBACK_ENV_VAR) == "1":
        return ocr
    return None


def _apply_ocr_fallback(data, dgp, tz):
    empty_ocr = DocxContent(paragraphs=[], tables=[])
    engine = _passport_ocr_engine()
    if engine is None:
        return [], empty_ocr, empty_ocr

    missing = [f for f in PASSPORT_FIELDS if f != "project_name" and data[f] is None]
    if not missing:
        return [], empty_ocr, empty_ocr

    needs_dgp_ocr = any(f in TEXT_FIELDS for f in missing)
    needs_tz_ocr = any(f == "building_class" or f in AREA_FIELDS for f in missing)

    dgp_lines = _ocr_lines(engine, dgp.images) if needs_dgp_ocr else []
    tz_lines = _ocr_lines(engine, tz.images) if needs_tz_ocr else []

    ocr_dgp = DocxContent(paragraphs=dgp_lines, tables=[])
    ocr_tz = DocxContent(paragraphs=tz_lines, tables=[])

    filled = []
    if data["address"] is None:
        value = extractors.extract_address(ocr_dgp)
        if value is not None:
            data["address"] = value
            filled.append("address")
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


def build_passport(project_name: str, dgp_path, tz_path) -> dict:
    dgp = read_docx(dgp_path)
    tz = read_docx(tz_path)
    data = {
        "project_name": project_name,
        "address": extractors.extract_address(dgp),
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


CONTRACT_PROBLEM_NOTHING_FOUND = "nothing_found"
CONTRACT_PROBLEM_COLUMN_UNKNOWN = "column_unknown"

# Below this much text, an engine has not read the page — it has returned the
# few stray marks it could make out. A protocol page holds thousands of
# characters; the scan that prompted this returned twelve.
MIN_READABLE_TEXT = 200

# The VAT rate is statutory rather than negotiated, so it's derived from the
# signing year instead of read off the protocol: 20% through 2025, 22% from
# 2026 on. A rate misread from a scan can't put a wrong figure in the
# passport this way.
VAT_RATE_CHANGE_YEAR = 2026
VAT_RATE_BEFORE_CHANGE = "20%"
VAT_RATE_FROM_CHANGE = "22%"


def vat_for_year(year_signed):
    """The VAT rate for a contract signed in ``year_signed``.

    Accepts the year as an int or as the string the passport stores it in.
    Returns None when no year is known, leaving the field to be filled by
    hand rather than guessing a rate.
    """
    if year_signed is None:
        return None
    match = re.search(r"\d{4}", str(year_signed))
    if not match:
        return None
    year = int(match.group())
    return VAT_RATE_FROM_CHANGE if year >= VAT_RATE_CHANGE_YEAR else VAT_RATE_BEFORE_CHANGE

# What to tell the user when a contract-terms upload fills nothing. Each
# message names the action that fixes it — an empty card with no
# explanation is indistinguishable from "the document had no such row".
#
# The three API messages are only ever reached once local OCR has also been
# tried and come back with nothing, so each one says so: otherwise "задайте
# ключ" would read as the only way forward, when in fact the offline path has
# already been down and failed, and typing the four values in is quicker than
# either.
CONTRACT_PROBLEM_MESSAGES = {
    CONTRACT_PROBLEM_NOTHING_FOUND: (
        "Файл прочитан, но ни одно условие распознать не удалось. "
        "Впишите значения вручную."
    ),
    CONTRACT_PROBLEM_COLUMN_UNKNOWN: (
        "Протокол составлен на несколько объектов, а какой столбец относится "
        "к этому проекту — определить не удалось: значения могут быть взяты "
        "из соседнего. Проверьте их, а лучше назовите проект так же, как "
        "объект назван в протоколе."
    ),
    ai_extractor.PROBLEM_NO_KEY: (
        "Это скан. Ключ API не настроен, а встроенное распознавание ничего "
        "не разобрало на странице. Впишите значения вручную — или задайте "
        "переменную окружения ANTHROPIC_API_KEY и загрузите файл заново."
    ),
    ai_extractor.PROBLEM_NO_CREDIT: (
        "Это скан. На счёте Anthropic нет средств, а встроенное распознавание "
        "ничего не разобрало на странице. Впишите значения вручную — или "
        "пополните баланс в разделе Plans & Billing и загрузите файл заново."
    ),
    ai_extractor.PROBLEM_API_ERROR: (
        "Это скан. Обратиться к быстрому распознаванию не удалось, а "
        "встроенное ничего не разобрало на странице. Впишите значения вручную "
        "— или проверьте подключение к сети и загрузите файл заново."
    ),
}


def _terms_from_text(text):
    """The four protocol conditions, read off whatever text we have — the
    PDF's own text layer or a page put through OCR. The patterns were written
    to cope with either."""
    return {
        "smr_term": contract_extractors.extract_smr_term(text),
        "advance_payment": contract_extractors.extract_advance_payment(text),
        "bank_guarantee": contract_extractors.extract_bank_guarantee(text),
        "performance_bond_pct": contract_extractors.extract_performance_bond(text),
    }


def _local_ocr_engines():
    """The OCR engines to try on a scan, fastest first.

    Windows' own engine reads a protocol page in about a second; EasyOCR takes
    minutes over the same page, so it only gets a turn if Windows can't help —
    the package missing, or the Russian language pack not installed.
    """
    engines = [win_ocr] if win_ocr.available() else []
    engines.append(ocr)
    return engines


def _terms_from_local_ocr(pdf_path, problem, project_name=None):
    """Read a scanned protocol with the OCR on this machine, after the API has
    already failed.

    Renders its own pages rather than reusing the ones sent to the API: those
    are capped to the size the API accepts, and on an A3 protocol the shrink
    costs exactly the small print the rates are written in.

    Runs without the OCR_FALLBACK_ENABLED opt-in that the passport fields
    need: by the time this is reached the fast path is already gone, so the
    choice isn't between a quick answer and a slow one but between a slow
    answer and none at all.

    Keeps the original problem code when OCR turns up nothing, so the page
    still names the thing that actually needs fixing.
    """
    images = pdf_reader.render_pages_to_images(pdf_path, max_long_edge=None)
    for engine in _local_ocr_engines():
        pages = [engine.recognize_page_words(image) for image in images]
        text, ambiguous = _protocol_text(pages, project_name)
        if len(text.strip()) < MIN_READABLE_TEXT:
            # Barely anything came back: this engine didn't read the page, so
            # the next one is worth its time.
            continue
        found = _terms_from_text(text)
        if any(value is not None for value in found.values()):
            return found, CONTRACT_PROBLEM_COLUMN_UNKNOWN if ambiguous else None
        # The page was read and simply doesn't say these things in words this
        # program knows. A second engine reading the same page differently
        # will not change that, and on this machine it costs six minutes of
        # the user staring at a page that appears to be doing nothing.
        return {}, CONTRACT_PROBLEM_NOTHING_FOUND
    return {}, problem


def _protocol_text(pages, project_name):
    """``(text, ambiguous)`` — the protocol as this project's own reading.

    A protocol drawn up for two objects has a column of conditions each; read
    flat they merge, and the term of works comes out as "38 месяцев ... 33
    месяца". Where the project's name matches one of the columns, only that
    one is kept.

    ``ambiguous`` is True when there were columns to choose between and the
    name matched none of them: the figures are then whatever both columns say
    together, which is worth admitting rather than presenting as this
    project's terms.
    """
    texts = []
    ambiguous = False
    for words in pages:
        kept, chosen = protocol_columns.keep_project_column(words, project_name)
        if not chosen and protocol_columns.is_multi_object(words):
            ambiguous = True
        texts.append("\n".join(ocr_lines.group_into_lines(kept)))
    return "\n".join(texts), ambiguous


def build_contract_terms(pdf_path, year_signed=None, project_name=None) -> tuple:
    """Best-effort extraction of the contract-terms protocol's fields.

    ``year_signed`` sets the VAT rate by rule (see ``vat_for_year``), which
    takes precedence over any rate found in the document.

    Returns ``(data, filled, problem)``. Tries the PDF's own text layer
    first (instant, regex-based). If the page turns out to be a scan with no
    text at all, asks Claude to read it directly as an image — much faster on
    this CPU-only setup than OCR, and it needs no opt-in since it isn't slow.
    Only if that fails does local OCR get its turn, slowly and offline.

    ``problem`` is None when at least one field was filled; otherwise it's a
    code from ``CONTRACT_PROBLEM_MESSAGES`` saying why, so the page can
    explain itself rather than showing a silently empty card. Whatever isn't
    found stays None, to be filled in by hand.
    """
    text = pdf_reader.read_pdf_text(pdf_path)
    problem = None
    if text.strip():
        found = _terms_from_text(text)
    else:
        images = pdf_reader.render_pages_to_images(pdf_path)
        found, problem = ai_extractor.extract_contract_terms_from_images(images)
        if problem is not None:
            found, problem = _terms_from_local_ocr(pdf_path, problem, project_name)

    data = {field: found.get(field) for field in CONTRACT_FIELDS}

    # Decide the warning on what the document itself gave up, before the VAT
    # rule adds a field of its own — otherwise a known signing year would
    # always suppress "nothing recognized".
    recognized = [f for f in CONTRACT_FIELDS if data[f] is not None]
    if problem is None and not recognized:
        problem = CONTRACT_PROBLEM_NOTHING_FOUND

    rate = vat_for_year(year_signed)
    if rate is not None:
        data["vat"] = rate

    filled = [f for f in CONTRACT_FIELDS if data[f] is not None]
    return data, filled, problem


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


def save_passport(passport_data: dict, path: Path) -> None:
    path.write_text(
        json.dumps(passport_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def price_per_sqm(data: dict):
    price = data.get("contract_price_rub")
    area = data.get("total_area_sqm")
    if price is None or not area:
        return None
    return price / area


def format_number(value):
    """Space-group a number's thousands for readability (10067050887.72 ->
    "10 067 050 887.72"), dropping ".00" for whole numbers. Passes through
    unchanged if ``value`` isn't a number, so it's safe to call on any
    passport field without checking the field's type first."""
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        return value
    formatted = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return formatted.replace(',', ' ')


def _format_money(value):
    formatted = f"{value:,.2f}"
    integer_part, _, decimal_part = formatted.partition('.')
    return integer_part.replace(',', ' ') + '.' + decimal_part


def _finalize_chart(rows):
    if rows:
        max_value = max(row["value"] for row in rows) or 1
        for row in rows:
            row["width_pct"] = round(row["value"] / max_value * 100, 1)
            row["display"] = _format_money(row["value"])
    return rows


def _chart_rows(passports, slugs, extra_field=None):
    rows = []
    for slug in slugs:
        data = passports[slug]
        price = data.get("contract_price_rub")
        if price is None:
            continue
        if extra_field is not None:
            extra = data.get(extra_field)
            if extra is None:
                continue
            label = f"{data.get('project_name') or slug} ({extra})"
        else:
            extra = None
            label = data.get("project_name") or slug
        rows.append({"slug": slug, "label": label, "value": price, "sort_key": extra})
    return rows


def build_comparison_charts(passports: dict, slugs: list) -> dict:
    """Bar-chart-ready rows for the compare page, one series per chart.

    Each row is independent magnitude data (price, or price per m²) for one
    project — projects missing the value(s) a given chart needs are skipped
    rather than shown as zero, since zero would misstate an unknown value.
    """
    price_by_year = _chart_rows(passports, slugs, extra_field="year_signed")
    price_by_year.sort(key=lambda row: row["sort_key"])

    price_by_class = _chart_rows(passports, slugs, extra_field="building_class")
    price_by_class.sort(key=lambda row: row["sort_key"])

    price = _chart_rows(passports, slugs)
    price.sort(key=lambda row: row["value"])

    price_per_sqm_rows = []
    for slug in slugs:
        data = passports[slug]
        value = price_per_sqm(data)
        if value is None:
            continue
        price_per_sqm_rows.append({
            "slug": slug, "label": data.get("project_name") or slug, "value": value,
        })
    price_per_sqm_rows.sort(key=lambda row: row["value"])

    return {
        "price_by_year": _finalize_chart(price_by_year),
        "price_by_class": _finalize_chart(price_by_class),
        "price": _finalize_chart(price),
        "price_per_sqm": _finalize_chart(price_per_sqm_rows),
    }


def load_passport(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    # A passport saved before a field existed (e.g. contract_price_rub)
    # won't have that key — backfill it as unset rather than making every
    # caller (templates included) handle a missing key.
    for field in PASSPORT_FIELDS + CONTRACT_FIELDS:
        data.setdefault(field, None)
    return data
