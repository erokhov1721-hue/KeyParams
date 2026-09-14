"""Bulk-import projects from the hand-maintained portfolio workbook.

That workbook (one sheet, "Проекты_НДС 20%") lays projects out as column
blocks rather than rows: each project gets a name in row 4 and its own run
of columns to the next project's, holding both passport-style fields (year
signed, class, contractor, areas — fixed row numbers, shared across every
block) and a full cost-by-work-type table with as many contract-amendment
versions as that project happens to have (variable, both in count and in
what each version is called — "ДС №9", "ДС на согласовании", a specific
date...). Parsing therefore reads passport fields by fixed row number, but
reads the cost table's columns by whatever row 24 actually says for that
block, rather than assuming a fixed set of versions.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from zipfile import BadZipFile

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from . import cost_increase, estimate_sections, predicted_increase, storage
from . import passport as passport_module
from .extractors import BUSINESS_PREMIUM_TOKEN
from .passport import BUILDING_CLASS_OPTIONS

SHEET_NAME = "Проекты_НДС 20%"

PROJECT_NAME_ROW = 4
FIRST_PROJECT_COLUMN = 3

# The "№" / work-type-name columns are shared by the whole sheet, one pair
# of columns to the left of where the first project's own columns start —
# not part of any individual project's column block.
NUMBER_COLUMN = 2
LABEL_COLUMN = 3

ROW_YEAR_SIGNED = 6
ROW_BUILDING_CLASS = 7
ROW_GENERAL_CONTRACTOR = 19
ROW_UNDERGROUND_AREA = 20
ROW_ABOVEGROUND_AREA = 21
ROW_TOTAL_AREA = 22

ROW_VERSION_HEADER = 24
FIRST_COST_ROW = 26
LAST_COST_ROW = 48

# Among however many amendment versions a project's block turns out to
# have, this is the one to treat as the baseline everywhere the imported
# data needs just one — chosen by the user over the others (ДГП, the
# various ДС) because it is the earliest, most settled figure.
PRIMARY_VERSION_LABEL = "Протокол ОУ"

# A secondary column repeats right after its version column with this same
# header text every time — it is that version's cost per square meter, not
# a version of its own, so it gets folded into the preceding version's key
# instead of standing as one.
PER_SQM_HEADER_PREFIX = "стоимость"

# Five «Паспорт договора» fields are read out of the cost table rather than
# any of the fixed passport rows above it — matched by row number, not by
# label text, since the sheet's own labels for these have typos
# ("Банковкская гаранития") that vary block to block. Row "2" is the "Under
# way / site costs" line, whose «Объем» cell states the СМР term in months
# as free text ("29 мес в тч ЗОС"); "2.1" and "2.2" are its bank-guarantee
# sub-items, whose «Объем» cell holds the guarantee's own percentage where
# one is known ("нет"/"да"/"предоставлено" otherwise). "2.1" (advance
# payment) is written down exactly as the cell has it either way — a plain
# "да"/"нет"/"предоставлено" answer is itself meaningful there, at the
# user's own call — and the same cell also answers bank_guarantee
# ("Банковская гарантия на возврат аванса"): a number means one was agreed,
# so "Включено"; the text states its own status directly. "2.2" (performance
# bond) keeps the percent-only, "no figure yet" reading — that field is
# specifically a percentage. vat comes from a different place entirely: the
# block's own «Итого ... с НДС N%» row states it in the row's label text,
# not in any cell value.
SMR_TERM_ROW_NUMBER = "2"
ADVANCE_PAYMENT_ROW_NUMBER = "2.1"
PERFORMANCE_BOND_ROW_NUMBER = "2.2"
VOLUME_COLUMN_KEY = "Объем"

# See ``apply_import``: these, unlike every other field this import writes,
# never overwrite a value the project already has.
CONTRACT_FIELDS_FILLED_ONLY_IF_EMPTY = {
    "smr_term", "advance_payment", "performance_bond_pct", "bank_guarantee", "vat",
}

# The photo embedded just below a project's name (row 4) anchors at that
# project's own start column in the workbook seen so far, but sometimes one
# column earlier instead — which side of a cell boundary the image's pixel
# offset happens to round to. Both are checked; neither is assumed.
_COVER_FORMAT_EXTENSIONS = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg"}


class MasterImportError(Exception):
    """The workbook isn't shaped like the portfolio import expects."""


def _cell(grid, row, col):
    """``grid[row][col]``, 1-indexed like the sheet, out-of-range as None.

    ``grid`` is the whole sheet read once via ``iter_rows(values_only=True)``
    rather than looked up cell by cell: a read-only worksheet's ``.cell()``
    re-walks its underlying XML stream on every random-access call, so at
    this sheet's width (280+ columns) repeated point lookups took minutes
    where one bulk read takes a second.
    """
    if row - 1 >= len(grid):
        return None
    line = grid[row - 1]
    if col - 1 >= len(line):
        return None
    return line[col - 1]


def _clean_text(value):
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


_CLASS_KEYWORD_RE = re.compile(r"бизнес|премиум|комфорт|эконом|элит|делюкс", re.IGNORECASE)
_BUSINESS_PREMIUM_RE = re.compile(BUSINESS_PREMIUM_TOKEN, re.IGNORECASE)
_CLASS_CANONICAL = {option.lower(): option for option in BUILDING_CLASS_OPTIONS}


def normalize_building_class(text):
    """Best-effort match of free text like "Жилая недвижимость (Бизнес)"
    onto one of ``BUILDING_CLASS_OPTIONS``. None if nothing recognisable is
    in there — a class outside that vocabulary (e.g. "класс А" office
    space) is left for manual entry rather than guessed at.
    """
    if not text:
        return None
    if _BUSINESS_PREMIUM_RE.search(text):
        return _CLASS_CANONICAL.get("бизнес - премиум", "Бизнес - Премиум")
    match = _CLASS_KEYWORD_RE.search(text)
    if not match:
        return None
    return _CLASS_CANONICAL.get(match.group(0).lower())


def extract_year(value):
    """A 4-digit year as a string, from a datetime, a bare year number, or
    free text like " Март 2024" — or None if nothing in ``value`` looks
    like one."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return str(value.year)
    if isinstance(value, (int, float)):
        year = int(value)
        return str(year) if 1900 <= year <= 2100 else None
    match = re.search(r"\d{4}", str(value))
    return match.group(0) if match else None


def _parse_passport(grid, col):
    return {
        "year_signed": extract_year(_cell(grid, ROW_YEAR_SIGNED, col)),
        "building_class": normalize_building_class(_cell(grid, ROW_BUILDING_CLASS, col)),
        "general_contractor": _clean_text(_cell(grid, ROW_GENERAL_CONTRACTOR, col)),
        "underground_area_sqm": _cell(grid, ROW_UNDERGROUND_AREA, col),
        "aboveground_area_sqm": _cell(grid, ROW_ABOVEGROUND_AREA, col),
        "total_area_sqm": _cell(grid, ROW_TOTAL_AREA, col),
    }


def _cost_columns(grid, start, end):
    """``[(column, key), ...]`` for the cost table's header row, in order.

    A "Стоимость на 1 м² ..." column has no version of its own — it repeats
    after whichever version column it belongs to — so it's keyed off that
    version's own label rather than its own (identical, ambiguous) text.
    """
    columns = []
    last_label = None
    for col in range(start, end):
        text = _clean_text(_cell(grid, ROW_VERSION_HEADER, col))
        if text is None:
            continue
        if text.lower().startswith(PER_SQM_HEADER_PREFIX) and last_label:
            columns.append((col, f"{last_label}, руб/м²"))
        else:
            columns.append((col, text))
            last_label = text
    return columns


def _parse_cost_table(grid, start, end):
    columns = _cost_columns(grid, start, end)
    rows = []
    for row in range(FIRST_COST_ROW, LAST_COST_ROW + 1):
        label = _clean_text(_cell(grid, row, LABEL_COLUMN))
        if label is None:
            continue
        number = _cell(grid, row, NUMBER_COLUMN)
        rows.append({
            "number": str(number) if number is not None else None,
            "label": label,
            "values": {key: _cell(grid, row, col) for col, key in columns},
        })
    return {
        "primary_version": PRIMARY_VERSION_LABEL,
        "columns": [key for _, key in columns],
        "rows": rows,
    }


def _primary_version_total(cost_table):
    """The primary version's (``Протокол ОУ``) total cost for the whole
    object — «Цена работ» — or None if the block has no «Итого» row for it.

    Not a sum of the block's own line items: on the real sheet that sum
    disagrees with the sheet's own printed total (line items include a few
    entries, like bank guarantees, that the printed «Итого» doesn't fold
    in), so only the sheet's own total row is trustworthy. A block can
    print more than one «Итого» row (a running subtotal, then a final one
    after a few more line items) — the last one is kept, since it's the
    most complete.
    """
    total = None
    for row in cost_table["rows"]:
        if "итого" not in row["label"].lower():
            continue
        value = row["values"].get(cost_table["primary_version"])
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total = value
    return total


_MONTHS_RE = re.compile(r"\d+")
# A construction term has to be within some plausible range of months — the
# real sheet has at least one block where this cell holds a stray cost
# figure (in the billions) instead of a month count, and that's obviously
# not a term to write down.
_PLAUSIBLE_SMR_MONTHS = range(1, 121)


def _smr_term_months(volume):
    """"29 мес в тч ЗОС" -> "29", or None if there's no number in ``volume``
    or it isn't a plausible month count."""
    if volume is None or isinstance(volume, bool):
        return None
    if isinstance(volume, (int, float)):
        months = int(volume)
    else:
        match = _MONTHS_RE.search(str(volume))
        if match is None:
            return None
        months = int(match.group())
    return str(months) if months in _PLAUSIBLE_SMR_MONTHS else None


def _volume_percent(volume):
    """"0.03" -> "3%" — a fraction read as a percentage. Text like
    "да"/"нет"/"предоставлено" means the sheet has no percentage there yet,
    so it's left for manual entry rather than guessed at."""
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        return None
    return f"{volume * 100:g}%"


def _advance_payment_value(volume):
    """The advance-payment guarantee row's «Объем» cell, as the sheet has
    it: "0.03" -> "3%" when it's a fraction, or the cell's own text
    ("да"/"нет"/"предоставлено") unchanged when it isn't. Unlike the
    performance-bond row, a plain yes/no answer here is meaningful on its
    own rather than standing in for a missing percentage — at the user's
    own call.
    """
    if volume is None or isinstance(volume, bool):
        return None
    if isinstance(volume, (int, float)):
        return f"{volume * 100:g}%"
    return _clean_text(volume)


def _bank_guarantee_status(volume):
    """"Банковская гарантия на возврат аванса", off the same «Объем» cell as
    advance_payment (2.1): a number means a guarantee percentage was
    actually agreed, hence "Включено"; text states its own status
    directly ("нет..." -> "Не включено", "включ.../да..." -> "Включено",
    anything else kept as written — "предоставлено" is already an answer
    on its own).
    """
    if volume is None or isinstance(volume, bool):
        return None
    if isinstance(volume, (int, float)):
        return "Включено"
    text = _clean_text(volume)
    if text is None:
        return None
    normalized = text.lower()
    if normalized.startswith(("не включ", "нет")):
        return "Не включено"
    if normalized.startswith(("включ", "да")):
        return "Включено"
    return text


_VAT_IN_LABEL_RE = re.compile(r"ндс\D{0,4}(\d+(?:[.,]\d+)?)\s*%", re.IGNORECASE)


def _vat_from_итого_row(cost_table):
    """The rate named in the block's own «Итого ... с НДС N%» row label —
    the only place a VAT rate is stated per block. Same row-selection as
    ``_primary_version_total`` (the last «Итого» row, if there's more than
    one), since it's the label of that same row being read here, just its
    text rather than its value.
    """
    label = None
    for row in cost_table["rows"]:
        if "итого" in row["label"].lower():
            label = row["label"]
    if label is None:
        return None
    match = _VAT_IN_LABEL_RE.search(label)
    return f"{match.group(1).replace(',', '.')}%" if match else None


def _row_by_number(cost_table, number):
    for row in cost_table["rows"]:
        if row["number"] == number:
            return row
    return None


def _contract_fields_from_cost_table(cost_table):
    smr_row = _row_by_number(cost_table, SMR_TERM_ROW_NUMBER)
    advance_row = _row_by_number(cost_table, ADVANCE_PAYMENT_ROW_NUMBER)
    bond_row = _row_by_number(cost_table, PERFORMANCE_BOND_ROW_NUMBER)
    advance_volume = advance_row["values"].get(VOLUME_COLUMN_KEY) if advance_row else None
    return {
        "smr_term": _smr_term_months(smr_row["values"].get(VOLUME_COLUMN_KEY)) if smr_row else None,
        "advance_payment": _advance_payment_value(advance_volume),
        "performance_bond_pct": (
            _volume_percent(bond_row["values"].get(VOLUME_COLUMN_KEY)) if bond_row else None
        ),
        "bank_guarantee": _bank_guarantee_status(advance_volume),
        "vat": _vat_from_итого_row(cost_table),
    }


def _parse_project_block(grid, start, end, cover=None):
    raw_name = _cell(grid, PROJECT_NAME_ROW, start)
    lines = [line.strip() for line in str(raw_name).splitlines() if line.strip()]
    passport = _parse_passport(grid, start)
    cost_table = _parse_cost_table(grid, start, end)
    passport["contract_price_rub"] = _primary_version_total(cost_table)
    passport.update(_contract_fields_from_cost_table(cost_table))
    return {
        "raw_name": " / ".join(lines) if lines else str(raw_name).strip(),
        "name_candidates": lines or [str(raw_name).strip()],
        "passport": passport,
        "cost_table": cost_table,
        "cover": cover,
    }


def _covers_by_start(ws, starts):
    """``{start_column: {"data": bytes, "ext": str}}`` for every project
    block that has a photo anchored at or one column before its own start —
    reading images at all requires the workbook loaded normally, not
    ``read_only``, which is why ``parse_workbook`` no longer uses that mode.
    """
    by_column = {}
    for image in getattr(ws, "_images", []):
        anchor_from = getattr(image.anchor, "_from", None)
        if anchor_from is None:
            continue
        by_column.setdefault(anchor_from.col, []).append(image)

    covers = {}
    for start in starts:
        image = None
        # Verified against the real workbook: an anchor's own column number
        # lands on ``start`` exactly about half the time and ``start - 1``
        # the other half, depending on which side of a cell boundary the
        # image's pixel offset rounds to — never anywhere else.
        for anchor_col in (start, start - 1):
            candidates = by_column.get(anchor_col)
            if candidates:
                image = candidates[0]
                break
        if image is None:
            continue
        ext = _COVER_FORMAT_EXTENSIONS.get(image.format)
        if ext is None:
            continue
        covers[start] = {"data": image._data(), "ext": ext}
    return covers


def parse_workbook(file) -> list:
    """Every project block on the portfolio sheet, in sheet order.

    ``file`` is anything ``openpyxl.load_workbook`` accepts (a path or a
    file-like object such as an uploaded file's stream). Raises
    ``MasterImportError`` if the file can't be opened as an .xlsx or lacks
    the expected sheet — never for a row or column this parser doesn't
    recognise, which it simply skips.
    """
    try:
        wb = openpyxl.load_workbook(file, data_only=True)
    except (InvalidFileException, BadZipFile, KeyError, OSError) as e:
        raise MasterImportError(f"Не удалось открыть файл как .xlsx: {e}") from e
    if SHEET_NAME not in wb.sheetnames:
        raise MasterImportError(f"В файле нет листа «{SHEET_NAME}»")
    ws = wb[SHEET_NAME]
    max_column = ws.max_column
    grid = list(ws.iter_rows(
        min_row=1, max_row=ws.max_row, max_col=max_column, values_only=True,
    ))

    starts = [
        col for col in range(FIRST_PROJECT_COLUMN, max_column + 1)
        if _cell(grid, PROJECT_NAME_ROW, col) not in (None, "")
    ]
    covers = _covers_by_start(ws, starts)
    blocks = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else max_column + 1
        blocks.append(_parse_project_block(grid, start, end, covers.get(start)))
    return blocks


# A project-type word the sheet sometimes puts on one side of the name and
# an existing project's own title may put on the other (or drop entirely) —
# stripped before comparing so it doesn't count as a mismatch.
_PROJECT_TYPE_PREFIX_RE = re.compile(r"^(жк|бц|мфк|тц|трц)\s+", re.IGNORECASE)
_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


def _match_key(name):
    text = _PROJECT_TYPE_PREFIX_RE.sub("", name.strip().lower())
    return _NON_WORD_RE.sub("", text)


def match_existing_slug(name_candidates, project_names):
    """The slug in ``project_names`` (``{slug: project_name}``) that
    ``name_candidates`` refers to, or None if it names a project that
    doesn't exist yet.

    The workbook's own name for a project splits across two lines in no
    consistent order (a short code then the familiar name, or the other
    way around), so every candidate line is tried. A match only counts
    when one normalised name contains the other in full — a partial,
    coincidental overlap would silently overwrite an unrelated project,
    while a missed match only costs a harmless extra project to clean up
    by hand, so the conservative failure mode is preferred here.
    """
    keys = [key for key in (_match_key(c) for c in name_candidates if c) if key]
    for slug, existing_name in project_names.items():
        if not existing_name:
            continue
        existing_key = _match_key(existing_name)
        if not existing_key:
            continue
        for key in keys:
            if key in existing_key or existing_key in key:
                return slug
    return None


def apply_import(root, parsed_projects) -> list:
    """Create or update a project for each entry ``parse_workbook``
    returned, matching by name against whatever is already in ``root``.

    Passport fields found in the workbook overwrite whatever was there
    before without checking who set it last — the user chose this
    deliberately, to keep the import simple, over protecting hand-verified
    fields the way a document re-upload does. ``address`` is never among
    the fields this import writes, since the workbook has none: an
    existing project's address is therefore never touched by it.
    ``contract_price_rub`` ("Цена работ") and the five «Паспорт договора»
    fields in ``CONTRACT_FIELDS_FILLED_ONLY_IF_EMPTY`` are the ones read out
    of the cost table rather than the fixed passport rows — see
    ``_primary_version_total`` and ``_contract_fields_from_cost_table``. The
    full cost-by-work-type table besides those numbers lands in its own file
    (``storage.master_import_path``), not mixed into ``passport.json`` or
    any real uploaded smeta. A cover photo, if the workbook had one for that
    project, replaces whatever cover the project already had — the same
    overwrite-outright choice as for the passport fields.

    The five «Паспорт договора» fields are the one exception to the
    overwrite-outright rule: they're filled only where the project doesn't
    already have a value, never overwriting one. Unlike the passport fields
    above, an existing value there most likely came from the project's own
    signed contract-terms protocol — a single, authoritative document this
    portfolio-wide summary sheet shouldn't second-guess.

    Returns one report entry per project: ``{"name", "slug", "action"}``,
    ``action`` being ``"created"`` or ``"updated"``.
    """
    # A snapshot of projects that existed *before* this run — not updated as
    # the loop below creates new ones. Two sheet entries can share one name
    # candidate by coincidence (two different buildings of the same "ЖК SET"
    # brand, two phases both on "Волоколамское ш."); matching against a
    # growing pool would let the second such entry silently fold itself into
    # the first, losing one of two real projects. A slug is also dropped
    # from the pool the moment it's matched, so it can't absorb a second,
    # unrelated entry later in the same run either.
    unmatched_existing = {
        slug: passport_module.load_passport(storage.passport_path(root, slug)).get("project_name")
        for slug in storage.list_project_slugs(root)
    }
    report = []
    for parsed in parsed_projects:
        slug = match_existing_slug(parsed["name_candidates"], unmatched_existing)
        if slug is None:
            name = parsed["raw_name"]
            slug = storage.create_project(root, name)
            passport_data = passport_module.build_passport(name)
            action = "created"
        else:
            del unmatched_existing[slug]
            passport_data = passport_module.load_passport(storage.passport_path(root, slug))
            action = "updated"
        for field, value in parsed["passport"].items():
            if value is None:
                continue
            if field in CONTRACT_FIELDS_FILLED_ONLY_IF_EMPTY and passport_data.get(field) is not None:
                continue
            passport_data[field] = value
        passport_module.save_passport(passport_data, storage.passport_path(root, slug))
        storage.master_import_path(root, slug).write_text(
            json.dumps(parsed["cost_table"], ensure_ascii=False, indent=2), encoding="utf-8",
        )
        cover = parsed.get("cover")
        if cover is not None:
            storage.save_cover_bytes(root, slug, cover["data"], cover["ext"])
        report.append({"name": passport_data.get("project_name") or slug, "slug": slug, "action": action})
    return report


# --- Reading the saved cost table back, as a fallback source for the
# project's смета/удорожание/coefficients -----------------------------------
#
# Everything below reads ``storage.master_import_path`` (written above by
# ``apply_import``) back into the same shapes the real per-project files
# would produce — ``estimate_sections.Section``, ``cost_increase.AmountLine``,
# ``predicted_increase.Line`` — so the callers in routes.py/excel_report.py
# can drop them in as one more source to try, behind the project's own real
# smeta/удорожание/prediction files and any hand-typed values, exactly the
# way ``CONTRACT_FIELDS_FILLED_ONLY_IF_EMPTY`` already defers to whatever's
# there first. Nothing here is ever the *only* source for anything; it only
# fires where the project has nothing more specific of its own.

# The version column the «смета» and «Итого ДС»/«Предполагаемое ДС» figures
# come from — not the primary version used for «Цена работ»: ДГП is what the
# user asked for here specifically, since it is the amount actually built
# into the current contract, where «Протокол ОУ» is the original one.
ESTIMATE_COST_COLUMN_KEY = "ДГП"
COST_INCREASE_COLUMN_KEY = "ИТОГО ДС"
PREDICTED_INCREASE_COLUMN_KEY = "Предполагаемое ДС"


def load_cost_table(root, slug):
    """The project's cost-by-work-type table as last imported, or None if
    it was never imported or the file can't be read. Never raises: this
    file is written only by ``apply_import`` itself, so a read failure
    means something odd happened to it after the fact, not a bad upload to
    explain to anyone.
    """
    path = storage.master_import_path(root, slug)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _row_amount(row, column_key):
    value = row["values"].get(column_key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def estimate_sections_from_cost_table(cost_table):
    """``[estimate_sections.Section, ...]`` from the table's own «ДГП»
    column, one per row — classified into a вид работ by
    ``estimate_sections.classify`` exactly the way a real смета's row names
    are, so a row this doesn't recognise (the bank-guarantee lines, the
    «Итого» row itself) is simply left out, the same as an unclassified
    смета row would be.

    The «Итого» rows are excluded explicitly, before ``classify`` ever sees
    them — not left to it returning ``None`` on its own. One workbook's
    closing line, «Итого СМР, в тч Отделка и Нулевой цикл...», contains
    «нулевой цикл» — one of ``shell_core``'s own match words — so without
    this check it read as that section, and the whole project's total got
    counted a second time as if it were «SHELL & CORE»'s own cost. Same
    failure mode ``read_sections`` already guards against in a real смета
    (see its own use of ``is_total_marker``), just reached from a different
    row shape.
    """
    sections = []
    for row in cost_table["rows"]:
        if estimate_sections.is_total_marker(row["label"]):
            continue
        key = estimate_sections.classify(row["label"])
        if key is None:
            continue
        amount = _row_amount(row, ESTIMATE_COST_COLUMN_KEY)
        if amount is None:
            continue
        sections.append(estimate_sections.Section(
            key=key, name=row["label"], amount=Decimal(str(amount)),
        ))
    return sections


def _volume_for_category(cost_table, category_key, label_hint):
    """The «Объем» cell of the one row that's both ``category_key`` and
    whose own label contains ``label_hint`` — a category can cover more
    than one row (``concrete`` also covers «Металлические конструкции»,
    which has no concrete volume of its own), so the category alone isn't a
    specific enough match.
    """
    for row in cost_table["rows"]:
        if estimate_sections.is_total_marker(row["label"]):
            continue
        if estimate_sections.classify(row["label"]) != category_key:
            continue
        if label_hint not in row["label"].lower():
            continue
        return _row_amount(row, VOLUME_COLUMN_KEY)
    return None


def concrete_volume_from_cost_table(cost_table):
    """Объём монолита, м³ — the «Ж/Б конструкции» row's own «Объем» cell."""
    return _volume_for_category(cost_table, "concrete", "ж/б")


def facade_area_from_cost_table(cost_table):
    """Площадь фасада, м² — the «Фасад» row's own «Объем» cell."""
    return _volume_for_category(cost_table, "facade", "фасад")


def _amount_lines_from_cost_table(cost_table, column_key, line_cls):
    """See ``estimate_sections_from_cost_table`` for why «Итого» rows are
    excluded before ``classify`` runs, not left to it alone."""
    lines = []
    for row in cost_table["rows"]:
        if estimate_sections.is_total_marker(row["label"]):
            continue
        key = estimate_sections.classify(row["label"])
        if key is None:
            continue
        amount = _row_amount(row, column_key)
        if amount is None:
            continue
        lines.append(line_cls(row["label"], Decimal(str(amount))))
    return lines


def cost_increase_lines_from_cost_table(cost_table):
    """``[cost_increase.AmountLine, ...]`` from the «ИТОГО ДС» column —
    the same shape ``cost_increase.build_report`` already accepts for a
    real «Итого ДС»-style удорожание file."""
    return _amount_lines_from_cost_table(
        cost_table, COST_INCREASE_COLUMN_KEY, cost_increase.AmountLine,
    )


def predicted_increase_lines_from_cost_table(cost_table):
    """``[predicted_increase.Line, ...]`` from the «Предполагаемое ДС»
    column — the same shape ``predicted_increase.build_report`` already
    accepts for a real прогнозируемое удорожание file."""
    return _amount_lines_from_cost_table(
        cost_table, PREDICTED_INCREASE_COLUMN_KEY, predicted_increase.Line,
    )
