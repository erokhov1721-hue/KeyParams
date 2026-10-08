import json
import os
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from . import (
    ai_extractor, contract_extractors, extractors, ocr, ocr_lines, pdf_reader,
    protocol_columns, tess_ocr, win_ocr,
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

BUILDING_CLASS_OPTIONS = [
    "Эконом", "Комфорт", "Бизнес", "Бизнес - Премиум", "Премиум", "Делюкс", "Элит",
    # Office real estate uses its own scale, not this residential one —
    # "Prime"/"Класс А"/"Класс Б", not "Эконом"/"Комфорт"/etc.
    "Prime", "Класс А", "Класс Б",
]

# The "Паспорт договора" card — filled from a separately uploaded contract
# terms protocol (often a PDF), independent of the object passport above.
CONTRACT_FIELDS = ["smr_term", "advance_payment", "bank_guarantee", "performance_bond_pct", "vat"]

CONTRACT_FIELD_LABELS = {
    "smr_term": "Срок СМР (мес.)",
    "advance_payment": "Аванс %",
    "bank_guarantee": "Банковская гарантия",
    "performance_bond_pct": "Performance bond, %",
    "vat": "НДС",
}

# Живёт в аккордеоне «Расчётные коэффициенты бетонных и фасадных
# конструкций» рядом с объёмом монолита, но считать его пока не из чего — до
# появления своего источника данных значение вписывается вручную, как когда-то
# и площади объекта.
REBAR_COEFFICIENT_FIELD = "rebar_coefficient_avg"

# Площадь фасада, вписанная вручную поверх того, что нашлось в смете. Смета
# не всегда режется на панели облицовки так, как это делает разбор, и в этом
# случае поправить цифру проще самому, чем чинить разбор под очередную новую
# смету.
FACADE_AREA_FIELD = "facade_area_manual"

# То же самое для объёма монолита: смета либо не загружена, либо устроена не
# так, как ждёт разбор («Возведение несущих конструкций здания» под другим
# заголовком, разбивка по уровням без такого раздела вовсе) — тогда объём
# вписывается вручную, поверх того, что нашлось в смете.
CONCRETE_VOLUME_FIELD = "concrete_volume_manual"

# Ручной флаг «проект завершён» — выставляется только руками (кнопкой на
# странице проекта), никакой разбор его не трогает. Без даты: пользователю
# нужен сам факт, а не когда именно он нажал кнопку.
COMPLETED_FIELD = "completed"

# Когда форма «Расчётных коэффициентов» в последний раз что-то сохранила —
# нет входа для имени, у приложения нет входа с SSO, поэтому дата хотя бы
# отвечает на вопрос «насколько свежее это ручное значение», раз уж на
# коэффициент, вписанный руками, полагается вся правдоподобность отчёта.
# Общая на все три поля формы: они всегда сохраняются одним сабмитом.
MANUAL_COEFFICIENTS_UPDATED_AT_FIELD = "manual_coefficients_updated_at"

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


_EMPTY_DOCX = DocxContent(paragraphs=[], tables=[], images=[])


def build_passport(project_name: str, dgp_path=None, tz_path=None) -> dict:
    """The passport auto-filled from the ДГП and ТЗ — either or both may be
    absent (``None``): a project can be created, or later completed, without
    one of them, and the fields the missing document would have supplied
    just stay unset for the fields below to fill in by hand, the same as a
    document that was read but had nothing for a particular field.
    """
    dgp = read_docx(dgp_path) if dgp_path is not None else _EMPTY_DOCX
    tz = read_docx(tz_path) if tz_path is not None else _EMPTY_DOCX
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
CONTRACT_PROBLEM_UNREADABLE = "unreadable"

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
    CONTRACT_PROBLEM_UNREADABLE: (
        "Не удалось прочитать файл — убедитесь, что это корректный PDF. "
        "Прежний протокол оставлен на месте."
    ),
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

# Почему замену ДГП отклонили — тем же способом, что и у файла удорожания:
# код в query-параметре, а не сообщение напрямую, чтобы произвольный
# ?dgp=... в адресной строке ничего на странице не показывал.
DGP_PROBLEM_MESSAGES = {
    "format": "Загрузите файл ДГП в формате .docx",
    "unreadable": (
        "Не удалось прочитать файл — убедитесь, что это корректный .docx. "
        "Прежний ДГП оставлен на месте."
    ),
}

TZ_PROBLEM_MESSAGES = {
    "format": "Загрузите файл ТЗ в формате .docx",
    "unreadable": (
        "Не удалось прочитать файл — убедитесь, что это корректный .docx. "
        "Прежний ТЗ оставлен на месте."
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
        lines, chosen = protocol_columns.project_lines(words, project_name)
        if not chosen and protocol_columns.is_multi_object(words):
            ambiguous = True
        texts.append("\n".join(lines))
    return "\n".join(texts), ambiguous


# --- распознавание протокола: каскад методов по полям ---
#
# Текстовый слой PDF читается всегда и первым. Дальше — методы для скана, в
# порядке из настройки: каждый следующий вызывается, только пока какого-то из
# четырёх полей протокола нет, и добирает только недостающие — найденное
# раньше не перезаписывает. Поле «не найдено», если значения нет или оно не
# прошло проверку (срок вне 1–120 месяцев, процент вне 0–100 и т. п.).

# The four conditions read off the protocol itself. VAT is not among them: it
# comes from the signing-year rule, and only Claude reads a rate off the page —
# counting it would send every scan without a year to the paid API for one
# figure the rule usually supplies anyway.
CONTRACT_OCR_FIELDS = ["smr_term", "advance_payment", "bank_guarantee", "performance_bond_pct"]

METHOD_TEXT = "text"
METHOD_TESSERACT = "tesseract"
METHOD_CLAUDE = "claude"
METHOD_WINDOWS = "windows"
METHOD_EASYOCR = "easyocr"
METHOD_RULE = "rule"

# How a method is named on the page, next to the value it found.
METHOD_LABELS = {
    METHOD_TEXT: "текст PDF",
    METHOD_TESSERACT: "Tesseract",
    METHOD_CLAUDE: "Claude",
    METHOD_WINDOWS: "Windows OCR",
    METHOD_EASYOCR: "EasyOCR",
    METHOD_RULE: "по году подписания",
}

SCAN_METHODS = (METHOD_TESSERACT, METHOD_CLAUDE, METHOD_WINDOWS, METHOD_EASYOCR)
LOCAL_SCAN_METHODS = (METHOD_TESSERACT, METHOD_WINDOWS, METHOD_EASYOCR)

# The order the scan methods are tried in, comma-separated — e.g.
# "windows,tesseract,claude,easyocr". Unknown names are ignored; a method
# left out is not used at all.
SCAN_ORDER_ENV = "KEYPARAMS_CONTRACT_SCAN_ORDER"
# The free methods on this machine first, the paid API after them; EasyOCR,
# minutes a page, last. Windows OCR exists only on Windows, so the server's
# default goes without it. (The Docker setup narrows it further — see
# docker-compose.yml — while the API account has no credit.)
DEFAULT_SCAN_ORDER = (
    (METHOD_TESSERACT, METHOD_WINDOWS, METHOD_CLAUDE, METHOD_EASYOCR)
    if sys.platform == "win32"
    else (METHOD_TESSERACT, METHOD_CLAUDE, METHOD_EASYOCR)
)

# A PDF can carry a text layer that holds only part of the protocol — a
# stamp, a header — with the conditions table pasted in as a picture. Set to
# 1, a text layer that leaves fields missing is followed by the scan methods
# for those fields; off by default, so a PDF with real text behaves exactly
# as before.
WEAK_TEXT_LAYER_ENV = "KEYPARAMS_CONTRACT_SCAN_WEAK_TEXT_LAYER"

# Bank-guarantee answers the passport takes as they are. Anything else — "Все
# авансы на счёт ОБС" — is a condition of its own, kept word for word and
# flagged for a person to look at rather than squeezed into a yes or no.
STANDARD_GUARANTEE = ("Включено", "Не включено")

# Why a value is flagged "проверьте" — and only these: a value is shown with
# its source always, but asked to be checked only when there is a reason.
REVIEW_NONSTANDARD = "nonstandard"
REVIEW_ZERO = "zero"
REVIEW_DISAGREE = "disagree"
REVIEW_REREAD = "reread"

CONTRACT_REVIEW_NOTE = "проверьте"

MONTHS_RANGE = (1, 120)
PERCENT_RANGE = (0, 100)
PERCENT_FIELDS = ("advance_payment", "performance_bond_pct")

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")

# How well a value can stand in the passport.
VALUE_OK = "ok"
VALUE_DOUBTFUL = "doubtful"   # kept, flagged, and the next method still asked
VALUE_INVALID = "invalid"     # counts as not found


def contract_scan_order():
    """The scan methods to try, in order, as configured."""
    raw = os.environ.get(SCAN_ORDER_ENV)
    if not raw or not raw.strip():
        return list(DEFAULT_SCAN_ORDER)
    order = []
    for name in raw.split(","):
        name = name.strip().lower()
        if name in SCAN_METHODS and name not in order:
            order.append(name)
    return order or list(DEFAULT_SCAN_ORDER)


def scan_weak_text_layer():
    return os.environ.get(WEAK_TEXT_LAYER_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _number(value):
    match = _NUMBER_RE.search(str(value))
    return float(match.group().replace(",", ".")) if match else None


def _normalized_term(field, value):
    """A value in the passport's own shape: a bare month count, a rate with
    its "%" — whichever method produced it. Claude in particular isn't bound
    by the anchors' patterns and may hand back "33 месяца" or "30 %"."""
    if value is None:
        return None
    if field == "smr_term":
        return contract_extractors.bare_number(str(value))
    if field == "advance_payment":
        return contract_extractors.percent_value(str(value))
    text = str(value).strip()
    return text or None


def assess_contract_value(field, value):
    """``VALUE_OK``, ``VALUE_DOUBTFUL`` or ``VALUE_INVALID``.

    Invalid — not found, the next method is asked: no value, a month count
    outside 1–120, a rate without its "%" or over 100. Doubtful — a 0% rate:
    a protocol can agree to no advance, but on a scan 0% is also what "30%"
    becomes when the 3 is lost, so it is kept, flagged, and the next method is
    still asked.
    """
    if value is None or not str(value).strip():
        return VALUE_INVALID
    if field == "smr_term":
        months = _number(value)
        ok = months is not None and MONTHS_RANGE[0] <= months <= MONTHS_RANGE[1]
        return VALUE_OK if ok else VALUE_INVALID
    if field in PERCENT_FIELDS:
        rate = _number(value)
        if "%" not in str(value) or rate is None or not PERCENT_RANGE[0] <= rate <= PERCENT_RANGE[1]:
            return VALUE_INVALID
        return VALUE_DOUBTFUL if rate == 0 else VALUE_OK
    return VALUE_OK


def contract_value_is_valid(field, value):
    """Whether ``value`` can stand in the passport as this field at all."""
    return assess_contract_value(field, value) != VALUE_INVALID


class _ScanPages:
    """The protocol's pages as pictures, rendered once per size and only when
    a method needs them: Claude gets pages capped to what the API takes, the
    local engines full-size ones (the shrink costs the small print the rates
    are written in), Tesseract its own 300 dpi."""

    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self._cache = {}

    def _get(self, key, **kwargs):
        if key not in self._cache:
            self._cache[key] = pdf_reader.render_pages_to_images(self.pdf_path, **kwargs)
        return self._cache[key]

    def for_api(self):
        return self._get("api")

    def for_local(self):
        return self._get("local", max_long_edge=None)

    def for_tesseract(self):
        return self._get("tesseract", resolution=tess_ocr.RENDER_DPI, max_long_edge=None)


class _MethodResult:
    """What one scan method gave: the fields it found, a problem code (Claude's
    reason for coming back empty), whether it read the page at all, whether
    its column choice was a guess, a note for the page, a VAT rate read off
    the document, and which fields it had to read again cell by cell."""

    def __init__(self, found=None, problem=None, read=False, ambiguous=False,
                 note=None, vat=None, reread=()):
        self.found = found or {}
        self.problem = problem
        self.read = read
        self.ambiguous = ambiguous
        self.note = note
        self.vat = vat
        self.reread = set(reread)


# A row's label carrying the percent sign — "Performance bond, %" — makes a
# bare figure in that row a rate: the sign the recogniser dropped from the
# value is still written once, in the label.
_PERCENT_ROW_LABELS = {
    "performance_bond_pct": contract_extractors.BOND_ANCHOR_RE,
}


def _percent_from_labelled_row(text, field):
    """A bare figure in the row whose label says "%" — "3" beside
    "Performance bond, %" — as that rate ("3%"), or None."""
    anchor = _PERCENT_ROW_LABELS[field]
    for line in text.splitlines():
        match = anchor.search(line)
        if not match:
            continue
        label_end = line.find("%", match.end())
        if label_end == -1:
            return None
        figure = _NUMBER_RE.search(line, label_end + 1)
        return f"{figure.group()}%" if figure else None
    return None


def _terms_from_scan_text(text):
    """``_terms_from_text``, plus a percent field the anchors missed because
    the recogniser dropped its "%" — taken when the row's label has one."""
    found = _terms_from_text(text)
    for field in _PERCENT_ROW_LABELS:
        if assess_contract_value(field, _normalized_term(field, found.get(field))) == VALUE_INVALID:
            found[field] = _percent_from_labelled_row(text, field) or found.get(field)
    return found


def _read_with_engine(engine, images, project_name):
    pages = [engine.recognize_page_words(image) for image in images]
    text, ambiguous = _protocol_text(pages, project_name)
    read = len(text.strip()) >= MIN_READABLE_TEXT
    return _MethodResult(
        found=_terms_from_scan_text(text) if read else {}, read=read, ambiguous=ambiguous,
    )


# Where a cell is read again when Tesseract's whole-page reading left its
# value out (or read a doubtful 0%): the label it sits beside, and the
# characters its value may hold (None — free text, for "Не включено").
_REREAD_CELLS = {
    "smr_term": (contract_extractors.SMR_ANCHOR_RE, "0123456789"),
    "advance_payment": (re.compile(r"аванс\w*\s*[,;]?\s*%", re.IGNORECASE), "0123456789%,."),
    "performance_bond_pct": (contract_extractors.BOND_ANCHOR_RE, "0123456789%,."),
    "bank_guarantee": (
        re.compile(r"банковск\w+\s+гаранти\w+\s+на\s+возврат\s+аванс\w*", re.IGNORECASE), None,
    ),
}


def _value_box(row, anchor, right_edge):
    """The part of a row to the right of its label — where the label's value
    sits — as ``(x0, y0, x1, y1)``, or None if the label isn't in the row."""
    ordered = sorted(row, key=lambda word: word.x0)
    text = ""
    starts = []
    for word in ordered:
        if text:
            text += " "
        starts.append(len(text))
        text += word.text
    match = anchor.search(text)
    if match is None:
        return None
    label_end = max(
        word.x1 for word, start in zip(ordered, starts) if start < match.end()
    )
    top = min(word.y - word.height / 2 for word in ordered)
    bottom = max(word.y + word.height / 2 for word in ordered)
    if right_edge - label_end < 10:
        return None
    return (label_end + 4, top, right_edge, bottom)


def _reread_value(field, raw):
    if field == "smr_term":
        return contract_extractors.bare_number(raw)
    if field == "bank_guarantee":
        return contract_extractors._normalized_guarantee(raw) if raw.strip() else None
    # A figure with its own "%" first; failing that, a bare one — the label
    # carries the "%" (it is how the cell was found), so it is that rate.
    with_sign = contract_extractors.PERCENT_FIGURE_RE.search(raw)
    number = contract_extractors.bare_number(with_sign.group() if with_sign else raw)
    return f"{number}%" if number is not None else None


def _row_text(row):
    return " ".join(word.text for word in sorted(row, key=lambda word: word.x0))


def _row_holds_advance_cap(row):
    return bool(re.search(r"не\s*закрыт\w*\s+аванс", _row_text(row), re.IGNORECASE))


def _wrapped_line_box(rows, index, label_box):
    """The line above the label's row, across the value's columns, if it is
    nothing but a figure ("30%," — or "0%," as Tesseract may misread it) —
    or None when it has a label of its own or there is none."""
    if index == 0:
        return None
    above = rows[index - 1]
    text = _row_text(above)
    if contract_extractors.LABEL_WORD_RE.search(text) or not re.search(r"\d", text):
        return None
    top = min(word.y - word.height / 2 for word in above)
    bottom = max(word.y + word.height / 2 for word in above)
    return (label_box[0], top, label_box[2], bottom)


def _reread_cells(pages, project_name, found):
    """Fields Tesseract's whole-page reading missed — or read as a doubtful
    0% — read again cell by cell: the region to the right of the field's
    label, as one line, digits only where the value is a figure. Only fields
    whose label was found get this, and a cell read back as 0% again is not
    taken over what was there."""
    rereads = {}
    for field, (anchor, whitelist) in _REREAD_CELLS.items():
        if assess_contract_value(field, _normalized_term(field, found.get(field))) == VALUE_OK:
            continue
        for words, page in pages:
            if page is None or not words:
                continue
            kept, _chosen = protocol_columns.keep_project_column(words, project_name)
            right_edge = max(word.x1 for word in kept)
            # On a protocol for several objects the image still holds the
            # other objects' columns: the cell is this object's column only.
            span = protocol_columns.project_column_span(words, project_name)
            value = None
            rows = protocol_columns.project_rows(words, project_name)
            for index, row in enumerate(rows):
                box = _value_box(row, anchor, right_edge)
                if box is None:
                    continue
                if field == "advance_payment" and _row_holds_advance_cap(row):
                    # The label's line holds only the cap on the unclosed
                    # advance — its figure is never the advance. The advance
                    # is the wrapped first line of the cell, just above, if
                    # that line is a bare figure with no label of its own.
                    box = _wrapped_line_box(rows, index, box)
                    if box is None:
                        break
                if span is not None:
                    box = (max(box[0], span[0]), box[1], min(box[2], span[1]), box[3])
                    if box[2] - box[0] < 10:
                        break
                value = _reread_value(field, tess_ocr.read_region(page, box, whitelist))
                break
            if assess_contract_value(field, value) == VALUE_OK:
                rereads[field] = value
                break
    return rereads


def _scan_with_tesseract(pages, project_name):
    available, reason = tess_ocr.availability()
    if not available:
        return _MethodResult(note=f"Tesseract недоступен: {reason}.")
    read_pages = tess_ocr.recognize_pages(pages.for_tesseract())
    text, ambiguous = _protocol_text([words for words, _page in read_pages], project_name)
    read = len(text.strip()) >= MIN_READABLE_TEXT
    if not read:
        return _MethodResult(note="Tesseract не смог прочитать страницы протокола.")
    found = _terms_from_scan_text(text)
    rereads = _reread_cells(read_pages, project_name, found)
    found.update(rereads)
    return _MethodResult(found=found, read=True, ambiguous=ambiguous, reread=rereads)


def _scan_with_claude(pages, project_name):
    images = pages.for_api()
    # Only named when there is a name: a caller (or a test) replacing the
    # function may still take the images alone.
    if project_name:
        found, problem = ai_extractor.extract_contract_terms_from_images(
            images, project_name=project_name,
        )
    else:
        found, problem = ai_extractor.extract_contract_terms_from_images(images)
    found = dict(found or {})
    # Claude is asked each figure as a rate ("аванс, %", "performance bond,
    # %"), so a bare number in its answer is that rate.
    for field in PERCENT_FIELDS:
        value = found.get(field)
        if value is not None and "%" not in str(value):
            found[field] = contract_extractors.percent_value(str(value))
    return _MethodResult(found=found, problem=problem, vat=found.get("vat"))


def _scan_with_windows(pages, project_name):
    if not win_ocr.available():
        return _MethodResult()
    return _read_with_engine(win_ocr, pages.for_local(), project_name)


def _scan_with_easyocr(pages, project_name):
    return _read_with_engine(ocr, pages.for_local(), project_name)


_SCAN_RUNNERS = {
    METHOD_TESSERACT: _scan_with_tesseract,
    METHOD_CLAUDE: _scan_with_claude,
    METHOD_WINDOWS: _scan_with_windows,
    METHOD_EASYOCR: _scan_with_easyocr,
}


class _Collected:
    """What the methods have found so far: each field's value and source, the
    fields still open to the next method (missing, or only a doubtful 0%),
    and the reasons to check a value."""

    def __init__(self):
        self.values = {}
        self.sources = {}
        self.doubtful = set()
        self.review = {}

    def flag(self, field, reason, text):
        self.review.setdefault(field, []).append({"reason": reason, "text": text})

    def open_fields(self):
        return [
            field for field in CONTRACT_OCR_FIELDS
            if field not in self.values or field in self.doubtful
        ]

    def take(self, method_found, method, reread=()):
        """Add the values ``method`` found for fields still open; returns the
        fields it settled or changed."""
        added = []
        for field in self.open_fields():
            value = _normalized_term(field, method_found.get(field))
            verdict = assess_contract_value(field, value)
            if verdict == VALUE_INVALID:
                continue
            if field in self.doubtful:
                if verdict != VALUE_OK:
                    continue  # another 0% changes nothing
                earlier = self.sources[field]
                self.flag(field, REVIEW_DISAGREE, (
                    f"способы разошлись: {METHOD_LABELS[earlier]} — {self.values[field]}, "
                    f"{METHOD_LABELS[method]} — {value}"
                ))
                self.doubtful.discard(field)
                self.review[field] = [
                    item for item in self.review[field] if item["reason"] != REVIEW_ZERO
                ]
            elif verdict == VALUE_DOUBTFUL:
                self.doubtful.add(field)
                self.flag(field, REVIEW_ZERO, f"{value} — проверьте, не потерялась ли цифра")
            self.values[field] = value
            self.sources[field] = method
            if field in reread:
                self.flag(field, REVIEW_REREAD, "значение прочитано повторно, отдельно по ячейке")
            added.append(field)
        return added


def _scan_cascade(pdf_path, project_name, collected):
    """Run the scan methods in the configured order for whatever ``collected``
    still lacks. Returns ``(problem, notes, vat)``: Claude's reason for coming
    back empty (or the column guess, or "nothing found"), notes for the page,
    and a VAT rate read off the document, if any."""
    pages = _ScanPages(pdf_path)
    api_problem = None
    ambiguous = False
    local_read = False
    notes = []
    vat = None
    for method in contract_scan_order():
        if not collected.open_fields():
            break
        # EasyOCR takes minutes on this machine. Once another engine here has
        # read the page, a second reading of the same page will not say what
        # the first couldn't find — only cost the wait.
        if method == METHOD_EASYOCR and local_read:
            continue
        result = _SCAN_RUNNERS[method](pages, project_name)
        if result.note:
            notes.append(result.note)
        if method == METHOD_CLAUDE and result.problem:
            api_problem = result.problem
        if result.read and method in LOCAL_SCAN_METHODS:
            local_read = True
        if collected.take(result.found, method, result.reread) and result.ambiguous:
            ambiguous = True
        if result.vat and vat is None:
            vat = result.vat

    if collected.values or vat:
        return (CONTRACT_PROBLEM_COLUMN_UNKNOWN if ambiguous else None), notes, vat
    if local_read:
        # The page was read and simply doesn't say these things in words this
        # program knows — that, not the API, is what there is to report.
        return CONTRACT_PROBLEM_NOTHING_FOUND, notes, vat
    return api_problem, notes, vat


def build_contract_terms(pdf_path, year_signed=None, project_name=None) -> tuple:
    """Best-effort extraction of the contract-terms protocol's fields.

    ``year_signed`` sets the VAT rate by rule (see ``vat_for_year``), which
    takes precedence over any rate found in the document.

    Returns ``(data, filled, problem)``. The PDF's own text layer is read
    first (instant, regex-based). A scan — no text layer at all, or, with
    ``WEAK_TEXT_LAYER_ENV`` on, one that left fields missing — goes
    through the scan methods in the configured order (``SCAN_ORDER_ENV``,
    by default Tesseract, Claude, Windows OCR, EasyOCR), each asked only
    for the fields still open; what an earlier one found stays, except a
    doubtful 0% that a later method reads as a real rate.

    ``data`` also carries, for the page: ``contract_sources`` — which method
    found each field; ``contract_review`` — per field, the reasons to check
    it (``{"reason", "text"}``: a non-standard condition kept word for word,
    a 0% rate, methods that disagreed, a cell read again on its own);
    ``contract_notes`` — what went wrong along the way (a missing Tesseract,
    say) that didn't stop the card from being filled.

    ``problem`` is None when at least one field was filled; otherwise it's a
    code from ``CONTRACT_PROBLEM_MESSAGES`` saying why, so the page can
    explain itself rather than showing a silently empty card. Whatever isn't
    found stays None, to be filled in by hand.
    """
    text = pdf_reader.read_pdf_text(pdf_path)
    collected = _Collected()
    problem = None
    notes = []
    vat = None
    if text.strip():
        collected.take(_terms_from_text(text), METHOD_TEXT)
        if collected.open_fields() and scan_weak_text_layer():
            problem, notes, vat = _scan_cascade(pdf_path, project_name, collected)
    else:
        problem, notes, vat = _scan_cascade(pdf_path, project_name, collected)

    data = {field: collected.values.get(field) for field in CONTRACT_FIELDS}
    sources = dict(collected.sources)
    if vat is not None and str(vat).strip():
        data["vat"] = str(vat).strip()
        sources["vat"] = METHOD_CLAUDE

    # Decide the warning on what the document itself gave up, before the VAT
    # rule adds a field of its own — otherwise a known signing year would
    # always suppress "nothing recognized".
    recognized = [f for f in CONTRACT_FIELDS if data[f] is not None]
    if problem is None and not recognized:
        problem = CONTRACT_PROBLEM_NOTHING_FOUND

    rate = vat_for_year(year_signed)
    if rate is not None:
        data["vat"] = rate
        sources["vat"] = METHOD_RULE

    guarantee = data.get("bank_guarantee")
    if guarantee and guarantee not in STANDARD_GUARANTEE:
        collected.flag(
            "bank_guarantee", REVIEW_NONSTANDARD,
            f"нестандартное условие, в протоколе: «{guarantee}»",
        )

    data["contract_sources"] = {f: m for f, m in sources.items() if data.get(f) is not None}
    data["contract_review"] = {f: items for f, items in collected.review.items() if items}
    data["contract_notes"] = notes
    filled = [f for f in CONTRACT_FIELDS if data[f] is not None]
    return data, filled, problem


def contract_review_items(review, field):
    """The reasons to check ``field`` as ``[{"reason", "text"}]`` — also for
    a passport saved before reasons existed, where the review held just the
    non-standard text."""
    items = (review or {}).get(field)
    if not items:
        return []
    if isinstance(items, str):
        return [{"reason": REVIEW_NONSTANDARD, "text": f"нестандартное условие, в протоколе: «{items}»"}]
    return list(items)


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
    # Written to a sibling temp file and swapped in with os.replace() rather
    # than written straight to path: a crash or a full disk mid-write must
    # not leave a truncated, unreadable passport.json in place of a working
    # one.
    text = json.dumps(passport_data, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class PassportConflictError(Exception):
    """Raised by ``save_passport_checked`` when the passport on disk has
    moved since ``expected_version`` was read — a second edit landed
    while this one was still open in a form, and saving it now would
    silently throw the other one away with nothing to show it ever
    happened."""


def save_passport_checked(passport_data: dict, path: Path, expected_version: int) -> None:
    """Like ``save_passport``, but refuses to overwrite a passport that
    has changed since ``expected_version`` — the version this
    ``passport_data`` was built from — was read; raises
    ``PassportConflictError`` instead.

    The filesystem gives no transaction across a read and a later write —
    every route that loads the passport, changes a field, and saves it
    back should go through this rather than ``save_passport`` directly,
    so two edits open on the same project at once don't let the second
    one to save quietly erase the first with no record either ever
    existed. Plays the same role an HTTP ETag would on a PUT, just as an
    integer counter instead, since nothing here needs to interoperate
    with an actual ETag header.
    """
    if path.exists():
        on_disk_version = load_passport(path).get("version", 0)
        if on_disk_version != expected_version:
            raise PassportConflictError(
                f"Паспорт {path} изменился с версии {expected_version} "
                f"(сейчас версия {on_disk_version}) — правка отклонена, "
                "чтобы не потерять чужую."
            )
    passport_data["version"] = expected_version + 1
    save_passport(passport_data, path)


def price_per_sqm(data: dict):
    price = data.get("contract_price_rub")
    area = data.get("total_area_sqm")
    if price is None or not area:
        return None
    return price / area


def concrete_coefficient(data: dict, concrete_volume):
    """The concrete volume (m³) over the object's total area — the same
    figure as the "Расчётные коэффициенты бетонных и фасадных конструкций"
    accordion on the project page. The volume is a parameter rather than
    read here from an estimate file, so this stays reusable wherever it's
    already at hand (the project page, the projects comparison).
    """
    area = data.get("total_area_sqm")
    if concrete_volume is None or not area:
        return None
    return concrete_volume / area


def facade_coefficient(data: dict, facade_area):
    """The estimate's proposed facade area (m²) over the object's total
    area — same idea as ``concrete_coefficient``, for facade cladding
    rather than monolithic concrete."""
    area = data.get("total_area_sqm")
    if facade_area is None or not area:
        return None
    return facade_area / area


def manual_coefficients_date_display(data: dict):
    """When the manual-coefficients form was last saved with at least one
    value in it, as "ДД.ММ.ГГГГ" — or None if nothing manual is set, or the
    stored date doesn't parse (an older passport, hand-edited JSON)."""
    stored = data.get(MANUAL_COEFFICIENTS_UPDATED_AT_FIELD)
    if not stored:
        return None
    try:
        return date.fromisoformat(stored).strftime("%d.%m.%Y")
    except ValueError:
        return None


def format_number(value):
    """Space-group a number's thousands for readability (10067050887.72 ->
    "10 067 050 887.72"), dropping ".00" for whole numbers. Passes through
    unchanged if ``value`` isn't a number, so it's safe to call on any
    passport field without checking the field's type first. A ``Decimal``
    (money, kept exact through its own arithmetic) is formatted the same
    as the equal float — display rounding to two places doesn't need the
    precision that arithmetic does."""
    if value is None:
        return None
    if not isinstance(value, (int, float, Decimal)):
        return value
    value = float(value)
    formatted = f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"
    return formatted.replace(',', ' ')


def _format_money(value):
    formatted = f"{value:,.2f}"
    integer_part, _, decimal_part = formatted.partition('.')
    return integer_part.replace(',', ' ') + '.' + decimal_part


# Largest unit first, so a value picks the first (and therefore biggest) one
# it clears rather than always bottoming out at thousands.
_MONEY_SCALE = [(1_000_000_000, "млрд"), (1_000_000, "млн"), (1_000, "тыс")]


def _format_money_short(value):
    """A rouble figure abbreviated to its largest round unit, two decimals —
    "24.16 млрд ₽" rather than every digit of "24 157 917 118.54". A bar
    chart's label has room for one of these, not the other; the full amount
    stays available as the row's own ``display``, meant for a tooltip.

    Falls back to the plain grouped amount below a thousand roubles, where
    abbreviating would lose the only digits that matter.
    """
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    for scale, suffix in _MONEY_SCALE:
        if magnitude >= scale:
            return f"{sign}{magnitude / scale:.2f} {suffix} ₽"
    return f"{sign}{_format_money(magnitude)} ₽"


def _format_rub_whole(value):
    """A per-unit rouble figure, grouped and rounded to the nearest rouble —
    "138 577 ₽". Small enough next to a project's name that full precision
    would just be visual noise the way it isn't on a bar chart."""
    return f"{round(value):,}".replace(",", " ") + " ₽"


def _finalize_chart(rows, kind="coefficient"):
    """Adds the display-ready fields every chart row needs, in place.

    ``kind`` picks the number format:
    - "money": a rouble amount too large to show in full next to its bar —
      ``display`` keeps full precision (a tooltip's job), ``short_display``
      is what's actually printed ("24.16 млрд ₽").
    - "money_per_sqm": a per-unit rouble amount (per m², per m³, ...) small
      enough to show whole; the unit is the chart's own title, not the
      row's, same as "coefficient" below.
    - "coefficient" (default): a plain 2-decimal number; the unit is the
      chart's own title, not the row's.

    Also flags a row whose value rounds to zero at the two decimals it's
    shown with: a sliver of a bar next to a value reading "0.00" looks like
    a rendering bug rather than "the estimate quotes almost nothing here",
    so the template swaps it for a dashed placeholder instead of a bar.
    """
    if not rows:
        return rows
    max_value = max(row["value"] for row in rows) or 1
    for row in rows:
        row["width_pct"] = round(row["value"] / max_value * 100, 1)
        row["is_zero"] = round(row["value"], 2) == 0
        if kind == "money":
            row["display"] = _format_money(row["value"]) + " ₽"
            row["short_display"] = _format_money_short(row["value"])
        elif kind == "money_per_sqm":
            row["display"] = _format_rub_whole(row["value"])
        else:
            row["display"] = _format_money(row["value"])
    return rows


# Tailwind's own -600 shades, so a project reads as the same colour on every
# chart and card on the compare page — not just a matching gradient — and a
# reader can tell "this one" from "that one" without checking the label.
# Rotates past its length for more than a handful of projects; distinct
# colours for a dozen at once isn't a promise this page makes.
PROJECT_COLOR_PALETTE = [
    "#059669",  # emerald-600
    "#4f46e5",  # indigo-600
    "#d97706",  # amber-600
    "#e11d48",  # rose-600
    "#0891b2",  # cyan-600
    "#7c3aed",  # violet-600
]


def project_colors(slugs: list) -> dict:
    """``{slug: hex}`` — a fixed colour per project, by its position in
    ``slugs``, stable across every chart and card on the page."""
    return {
        slug: PROJECT_COLOR_PALETTE[i % len(PROJECT_COLOR_PALETTE)]
        for i, slug in enumerate(slugs)
    }


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


def _value_chart_rows(passports, slugs, value_fn):
    """Chart rows for a per-project value not carried straight off the
    estimate's own price — a coefficient, say, rather than a rouble figure.
    Projects the value function returns None for are skipped, same as
    everywhere else on this page: a missing value isn't a zero."""
    rows = []
    for slug in slugs:
        value = value_fn(slug)
        if value is None:
            continue
        rows.append({
            "slug": slug, "label": passports[slug].get("project_name") or slug,
            "value": value,
        })
    rows.sort(key=lambda row: row["value"])
    return rows


def build_comparison_charts(
    passports: dict, slugs: list,
    concrete_coefficients: dict = None, facade_coefficients: dict = None,
    concrete_materials_per_m3: dict = None, concrete_works_per_m3: dict = None,
) -> dict:
    """Bar-chart-ready rows for the compare page, one series per chart.

    Each row is independent magnitude data (price, or price per m²) for one
    project — projects missing the value(s) a given chart needs are skipped
    rather than shown as zero, since zero would misstate an unknown value.

    ``concrete_coefficients``, ``facade_coefficients``,
    ``concrete_materials_per_m3`` and ``concrete_works_per_m3`` are ``{slug:
    value}`` computed from each project's estimate — unlike the rest, they
    can't be read straight off ``passports``.
    """
    concrete_coefficients = concrete_coefficients or {}
    facade_coefficients = facade_coefficients or {}
    concrete_materials_per_m3 = concrete_materials_per_m3 or {}
    concrete_works_per_m3 = concrete_works_per_m3 or {}

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
        "price_by_year": _finalize_chart(price_by_year, kind="money"),
        "price_by_class": _finalize_chart(price_by_class, kind="money"),
        "price": _finalize_chart(price, kind="money"),
        "price_per_sqm": _finalize_chart(price_per_sqm_rows, kind="money_per_sqm"),
        "concrete_coefficient": _finalize_chart(_value_chart_rows(
            passports, slugs, lambda slug: concrete_coefficients.get(slug)
        )),
        "facade_coefficient": _finalize_chart(_value_chart_rows(
            passports, slugs, lambda slug: facade_coefficients.get(slug)
        )),
        "rebar_coefficient": _finalize_chart(_value_chart_rows(
            passports, slugs, lambda slug: passports[slug].get("rebar_coefficient_avg")
        )),
        "concrete_materials_per_m3": _finalize_chart(_value_chart_rows(
            passports, slugs, lambda slug: concrete_materials_per_m3.get(slug)
        ), kind="money_per_sqm"),
        "concrete_works_per_m3": _finalize_chart(_value_chart_rows(
            passports, slugs, lambda slug: concrete_works_per_m3.get(slug)
        ), kind="money_per_sqm"),
    }


class PassportReadError(Exception):
    """passport.json exists but can't be read — corrupted JSON, a bad
    encoding, or the file itself has gone missing or unreadable between the
    directory listing and the read. One error type for every caller to
    handle the same way, rather than each deciding for itself which of
    json.JSONDecodeError/UnicodeDecodeError/OSError it's willing to catch."""


def load_passport(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        raise PassportReadError(f"Не удалось прочитать паспорт {path}: {e}") from e
    # A passport saved before a field existed (e.g. contract_price_rub)
    # won't have that key — backfill it as unset rather than making every
    # caller (templates included) handle a missing key.
    for field in PASSPORT_FIELDS + CONTRACT_FIELDS + [
        REBAR_COEFFICIENT_FIELD, FACADE_AREA_FIELD, CONCRETE_VOLUME_FIELD,
        MANUAL_COEFFICIENTS_UPDATED_AT_FIELD,
    ]:
        data.setdefault(field, None)
    # A flag, not "unknown" text/number like the fields above — a passport
    # saved before it existed was, definitionally, not yet marked complete.
    data.setdefault(COMPLETED_FIELD, False)
    # An integer counter, not None like the rest above: save_passport_checked
    # compares it directly, and a passport saved before it existed is
    # unambiguously at the start of the count, not at an unknown version.
    data.setdefault("version", 0)
    return data
