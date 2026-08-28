"""Reading an estimate's top-level sections into the report's cost lines.

A tender offer is a few thousand rows deep, but the comparison only wants
seventeen numbers: the total of each top-level section, laid against the line
it belongs to. The offer carries its own hierarchy in a "№ раздела" column —
1, 1.1, 1.2.3 — so the sections are the rows numbered with a bare integer,
and everything under them is already summed into them.

Which line a section belongs to is decided by its name rather than by its
number: the numbering is per-workbook and drifts (an offer whose sections run
1..15 numbers its own articles 1, 2, ... 12, 13, 99, 14, 16), while the names
are the industry's and stay put.
"""

import logging
import re
from collections import namedtuple
from decimal import Decimal
from pathlib import Path

from . import extractors, workbook_cache

logger = logging.getLogger(__name__)

# The report's cost lines, in the order they appear on the sheet, each with
# the words that identify its section in an estimate. First match wins, so
# order matters where names overlap: "Общестроительные работы (без отделки)"
# has to be claimed by the partitions line before the finishing line can see
# the word "отдел" in it.
CATEGORY_RULES = [
    ("rd", ("рабочей документации", "рабочая документация", "стадии \"р\"",
            "стадии р", "проектирование")),
    ("preparation", ("подготовительные работы", "содержание площадки")),
    ("excavation", ("котлован",)),
    ("waterproofing", ("гидроизоляц",)),
    ("concrete", ("конструктивные решения", "монолит", "несущих конструкций",
                  "конструкций здания")),
    ("partitions", ("общестроительные", "перегородк")),
    ("facade", ("фасад",)),
    ("roof", ("кровля", "кровли")),
    # Not a bare "отделка": the flats' own finishing is a package of its own
    # ("отделка квартир" = MR Base) and must not be swept in with the finishing
    # of the common areas.
    ("finishing", ("отделочные работы", "отделка моп", "отделка паркинга",
                   "отделка мест общего", "внутреняя отделка", "внутренняя отделка")),
    ("lifts", ("лифт",)),
    ("utilities", ("инженерн", "вис")),
    ("landscaping", ("благоустройств",)),
    ("technology", ("технологическ", "тх")),
    ("other", ("прочее", "зип", "другие", "дополнительные работы")),
    ("mr_base", ("mr-base", "mr base", "отделка квартир", "квартир")),
    ("mr_ready", ("mr-ready", "mr ready")),
    ("shell_core", ("shell", "нулевого цикла", "нулевой цикл")),
]

CATEGORY_KEYS = [key for key, _ in CATEGORY_RULES]

# What each line is called where a person reads it — the customer's own
# wording, from their comparison sheet. Kept here rather than beside either
# of the things that display it, so the Excel export and the page in the
# browser cannot end up naming the same line differently.
CATEGORY_LABELS = {
    "rd": 'Разработка стадии "Р"',
    "preparation": (
        "Подготовительные работы и содержание площадки (включая содержание "
        "прилегающей территории, аренда оборудования и механизмов и т.п.)"
    ),
    "excavation": "Устройство котлована",
    "waterproofing": "Гидроизоляция подземной части",
    "concrete": "Монолит + МК",
    "partitions": "Перегородки и стены",
    "facade": "Фасад",
    "roof": "Кровли",
    "finishing": "Отделка МОП, двери, ворота",
    "lifts": "Лифты",
    "utilities": "Инженерные системы",
    "landscaping": "Благоустройство",
    "technology": "Технологические решения",
    "other": "Другие (ЗИП и т.д.)",
    "mr_base": "MR Base",
    "mr_ready": "MR Ready",
    "shell_core": "SHELL & CORE",
}

# The last three lines are the finishing packages, which the sheet sets apart
# from the fourteen numbered kinds of work.
MR_CATEGORY_KEYS = ["mr_base", "mr_ready", "shell_core"]
WORK_CATEGORY_KEYS = [key for key in CATEGORY_KEYS if key not in MR_CATEGORY_KEYS]

# How far down to look for the header: an offer opens with the tender's name,
# the object, the address and the bidder's details before the table starts.
HEADER_SEARCH_ROWS = 40
HEADER_SEARCH_COLS = 40

SECTION_HEADER = "раздел"
# The stem, not the word: one offer heads the column "Статья СМР" and another
# "Справочник статей СМР", and matching the nominative alone left the second
# without an article column and so without any sections at all.
ARTICLE_HEADER = "стат"
ITEM_HEADER = "п/п"
NAME_HEADER = "наименование"
TOTAL_HEADER = "стоимость всего"
TOTAL_SUBHEADER = "всего"

# A section number, as opposed to a sub-section: "4" is one, "4.1" is part of
# it and is already counted inside it.
TOP_LEVEL_RE = re.compile(r"^\d+$")
# The article number an estimate prefixes its section name with ("12.
# Благоустройство"), dropped before matching so a renumbered offer still
# lands on the same line.
LEADING_NUMBER_RE = re.compile(r"^[\d.]+\s*")


class EstimateSectionsError(Exception):
    pass


class FormulaWithoutCacheError(EstimateSectionsError):
    """A cell holds a formula Excel never saved a computed result for.

    ``data_only=True`` reads that cell as ``None`` — the same as a cell with
    nothing in it at all — and a reader that can't tell the two apart either
    drops a section's cost silently or, worse, keeps reading formula cells
    from other rows and ends up with a report that looks complete but isn't.
    """


class _CheckedSheet:
    """A worksheet paired with its own formula-only twin (the same file
    loaded a second time with ``data_only=False``), so ``amount_at`` can
    tell "genuinely empty" apart from "a formula with no cached value" —
    everything else about the sheet (``cell``, ``max_row``, ``title``, ...)
    passes straight through to the ``data_only=True`` worksheet unchanged.
    """

    def __init__(self, ws, ws_formulas):
        self._ws = ws
        self._ws_formulas = ws_formulas

    def __getattr__(self, name):
        return getattr(self._ws, name)

    def _parsed_at(self, row, column, parse):
        value = self._ws.cell(row=row, column=column).value
        if value is not None:
            return parse(value)
        raw = self._ws_formulas.cell(row=row, column=column).value
        if isinstance(raw, str) and raw.startswith("="):
            coord = self._ws.cell(row=row, column=column).coordinate
            raise FormulaWithoutCacheError(
                f'Ячейка {coord} на листе «{self._ws.title}» — формула без '
                'сохранённого значения. Откройте файл в Excel, дайте ему '
                'пересчитаться (или просто сохраните заново) и загрузите его '
                'ещё раз.'
            )
        return None

    def amount_at(self, row, column):
        """The number in this cell, as ``float`` — via ``_amount`` — or
        None if it is genuinely empty. Raises ``FormulaWithoutCacheError``
        if the cell holds an uncached formula instead. For a quantity (a
        volume, an area) — ``money_at`` is the one for a cost total."""
        return self._parsed_at(row, column, _amount)

    def money_at(self, row, column):
        """Like ``amount_at``, but as ``Decimal`` — for a cost total,
        which gets summed across many rows and must not pick up a
        binary float's rounding on top of that."""
        return self._parsed_at(row, column, _decimal_amount)


def _checked_sheets(path, error_type=None):
    """Every worksheet of ``path``, paired with its formula-only twin — the
    same workbook loaded once with cached values and once without, zipped
    sheet by sheet so ``amount_at`` has both views of the same cell.
    """
    error_type = error_type or EstimateSectionsError
    try:
        # Not read_only: the header spans merged cells, and a streaming
        # worksheet doesn't carry the merges needed to tell the two
        # cost blocks apart. Cached per (path, mtime, size): a project page
        # reads this same file several times over (concrete volume, facade
        # area, section costs), and re-parsing it from disk every time was
        # the single most expensive thing the page did.
        wb = workbook_cache.get_or_load(path, data_only=True)
        wb_formulas = workbook_cache.get_or_load(path, data_only=False)
    except Exception as e:
        raise error_type(f"Cannot read {path}: {e}") from e
    return [
        _CheckedSheet(ws, ws_formulas)
        for ws, ws_formulas in zip(wb.worksheets, wb_formulas.worksheets)
    ]


_LETTER_RE = re.compile(r"[a-zа-яё]", re.IGNORECASE)


def _named(value):
    """The value as a name, or None if it is only a number or a code."""
    text = str(value or "").strip()
    return text if _LETTER_RE.search(text) else None


def _cell_text(ws, row, col):
    value = ws.cell(row=row, column=col).value
    return str(value).strip().lower() if value is not None else ""


def _heading_block(ws, row, col):
    """The columns a heading covers: up to just before the next heading.

    Read from the headings themselves rather than from the merged cells they
    are usually written in — one offer left "Стоимость всего" unmerged, and a
    reader that insisted on the merge found no totals column at all and gave
    up on the whole workbook.
    """
    for following in range(col + 1, HEADER_SEARCH_COLS + 1):
        if _cell_text(ws, row, following):
            return col, following - 1
    return col, HEADER_SEARCH_COLS


def _find_total_column(ws, header_row):
    """The column holding each section's total cost.

    An offer states costs twice over — per unit and in total — under headings
    with the same four sub-columns beneath each, so the heading alone doesn't
    identify a column: the one wanted is the "Всего" under "Стоимость всего".
    "Стоимость всего за объёмы заказчика" stands alongside with nothing
    underneath it, and is passed over for exactly that reason.
    """
    for col in range(1, HEADER_SEARCH_COLS + 1):
        if TOTAL_HEADER not in _cell_text(ws, header_row, col):
            continue
        first, last = _heading_block(ws, header_row, col)
        for sub in range(first, last + 1):
            if _cell_text(ws, header_row + 1, sub) == TOTAL_SUBHEADER:
                return sub
    return None


Header = namedtuple(
    "Header", "row item_col section_col article_col name_col total_col",
)

# One section of an estimate, already placed on a report line: ``key`` is the
# line, ``name`` the section as the estimate spells it. The name is carried
# along so the report can say where a figure came from — the placement is a
# judgement about wording, and a judgement nobody can check is worth little.
Section = namedtuple("Section", "key name amount")


def _find_header(ws):
    """Where the table starts and which columns matter, or None if this
    workbook isn't an offer laid out with numbered sections.

    The name column is found alongside the article column because a section is
    not always named in the one meant for it — in a real offer one section of
    fifteen had its "Статья СМР" cell left blank and only the works name
    filled in, and dropping it would have quietly lost 1.9 billion roubles
    from the report.
    """
    for row in range(1, HEADER_SEARCH_ROWS + 1):
        item_col = section_col = article_col = name_col = None
        for col in range(1, HEADER_SEARCH_COLS + 1):
            text = _cell_text(ws, row, col)
            if item_col is None and ITEM_HEADER in text:
                item_col = col
            elif section_col is None and SECTION_HEADER in text:
                section_col = col
            elif article_col is None and ARTICLE_HEADER in text:
                article_col = col
            elif name_col is None and NAME_HEADER in text:
                name_col = col
        if section_col is None or article_col is None:
            continue
        total_col = _find_total_column(ws, row)
        if total_col is not None:
            return Header(row, item_col, section_col, article_col, name_col, total_col)
    return None


def _amount(value):
    """The number in a total cell. A zero is a number like any other: written
    as ``value or ""`` this quietly dropped every section that came to nothing,
    and a section costing nothing is exactly what the report wants to show."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return extractors.parse_number(str(value))


def _decimal_amount(value):
    """Like ``_amount``, but as ``Decimal`` — for a cost total. openpyxl
    hands back a plain ``float`` for a numeric cell regardless (Excel's own
    storage is float64 too, so this can't undo whatever precision was
    already lost getting the number into the spreadsheet in the first
    place) — ``Decimal(str(value))`` at least stops at the float's own
    shortest round-tripping decimal rather than spelling out its exact
    binary value, so summing many of these together doesn't compound a
    second layer of rounding on top of Excel's.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return extractors.parse_money(str(value))


def classify(name: str):
    """The report line a section with this name belongs to, or None."""
    text = LEADING_NUMBER_RE.sub("", str(name or "").strip().lower())
    if not text:
        return None
    for key, tokens in CATEGORY_RULES:
        for token in tokens:
            # Short tokens are matched as whole words: "ТХ" is a section of
            # its own, but as a substring it also sits inside "отходов".
            if len(token) <= 3:
                if re.search(rf"\b{re.escape(token)}\b", text):
                    return key
            elif token in text:
                return key
    return None


def read_section_totals(path) -> dict:
    """``{category key: total cost}`` for one estimate.

    Only the lines the estimate actually has appear in the result — a section
    it doesn't carry stays absent rather than becoming a zero, so the report
    can tell "nothing was spent here" from "this estimate doesn't say".
    """
    totals = {}
    for section in read_sections(path):
        totals[section.key] = totals.get(section.key, Decimal("0")) + section.amount
    return totals


def read_sections(path) -> list:
    """Every section of one estimate that has a line in the report.

    Returns an empty list for a workbook that isn't laid out as a sectioned
    offer at all: the report then leaves its cost lines blank, exactly as it
    did before any estimate was attached.
    """
    return read_sections_with_warnings(path)[0]


def read_sections_with_warnings(path):
    """(sections, unmatched) — ``read_sections``, plus the section names on
    the sheet actually used that ``classify`` couldn't place on a report
    line, so a section quietly going missing from the report can be shown
    to whoever is looking at the page, not just logged.
    """
    path = Path(path)
    for ws in _checked_sheets(path):
        sections, unmatched = _sections_from_sheet(ws)
        if sections:
            _report_unmatched(unmatched)
            return sections, unmatched
    return [], []


LEVEL_HEADER = "уровень"
LEVEL_TOTAL_HEADER = "всего"
# Не «предлагаемое количество», как в оффере — в укрупнённой смете колонка
# названа просто «количество».
LEVELS_QTY_HEADER = "количество"

Levels = namedtuple("Levels", "row first second third total_col qty_col unit_col")


def _find_levels_header(ws):
    """Where a "укрупнённая смета" states its levels, or None.

    A different shape of estimate from the offer above: instead of one column
    of section numbers it gives a column pair per level of nesting — "номер 1"
    and "уровень 1", "номер 2" and "уровень 2", and so on — with the money in
    a "Всего" column of its own, and (where the estimate carries one) the
    proposed quantity in a "количество" column next to a unit-of-measure
    column of its own.
    """
    for row in range(1, HEADER_SEARCH_ROWS + 1):
        levels, total_col, qty_col, unit_col = [], None, None, None
        for col in range(1, HEADER_SEARCH_COLS + 1):
            text = _cell_text(ws, row, col)
            if text.startswith(LEVEL_HEADER):
                levels.append(col)
            elif total_col is None and text.startswith(LEVEL_TOTAL_HEADER):
                total_col = col
            elif qty_col is None and LEVELS_QTY_HEADER in text:
                qty_col = col
            elif unit_col is None and all(token in text for token in UNIT_HEADER_TOKENS):
                unit_col = col
        if len(levels) >= 2 and total_col is not None:
            return Levels(
                row=row, first=levels[0], second=levels[1],
                third=levels[2] if len(levels) > 2 else None,
                total_col=total_col, qty_col=qty_col, unit_col=unit_col,
            )
    return None


def _sections_from_levels(ws):
    """Section totals from an estimate written in levels.

    The money sits at the deepest level that has any: a section's own row is
    usually empty, and so is the row of a sub-section whose parts are listed
    beneath it. Each sub-section is therefore taken at its own figure where it
    has one, and as the sum of its parts where it hasn't — which is the one
    reading that neither loses money nor counts it twice.
    """
    header = _find_levels_header(ws)
    if header is None:
        return [], []

    sections, unmatched = [], []
    current_key = current_name = None
    current_own = None      # сумма, записанная на самой строке раздела
    total = Decimal("0")
    pending = None          # (собственная сумма подраздела, сумма его частей)

    def close_subsection():
        nonlocal total, pending
        if pending is not None:
            own, parts = pending
            total += own if own is not None else parts
            pending = None

    def close_section():
        nonlocal current_key, current_own, total
        close_subsection()
        if current_key is not None:
            # A section that states its own total is taken at its word; one
            # that leaves the cell empty is the sum of what is listed under it.
            sections.append(Section(
                current_key, current_name,
                current_own if current_own is not None else total,
            ))
        current_key, current_own, total = None, None, Decimal("0")

    for row in range(header.row + 1, ws.max_row + 1):
        amount = ws.money_at(row, header.total_col)
        first = _named(ws.cell(row=row, column=header.first).value)
        second = _named(ws.cell(row=row, column=header.second).value)
        third = (
            _named(ws.cell(row=row, column=header.third).value)
            if header.third else None
        )

        if first:
            close_section()
            key = classify(first)
            if key is None:
                unmatched.append(first)
                current_name = None
            else:
                current_key, current_name, current_own = key, first, amount
            continue
        if current_key is None:
            continue
        if second:
            close_subsection()
            pending = (amount, Decimal("0"))
        elif pending is not None and amount is not None:
            own, parts = pending
            pending = (own, parts + amount)
        elif amount is not None and third:
            total += amount

    close_section()
    return sections, unmatched


def _report_unmatched(unmatched):
    if unmatched:
        # Not an error: an estimate may carry sections this report has no line
        # for. Logged so a section quietly going missing can be traced — and
        # surfaced to read_sections_with_warnings' caller, so it doesn't only
        # show up in a log nobody in production reads.
        logger.info("Разделы сметы без строки в отчёте: %s", "; ".join(unmatched))


def _sections_from_sheet(ws):
    sections, unmatched = _sections_from_offer(ws)
    if sections:
        return sections, unmatched
    return _sections_from_levels(ws)


def _sections_from_offer(ws):
    header = _find_header(ws)
    if header is None:
        return [], []

    sections = []
    unmatched = []
    started = False
    for row in range(header.row + 2, ws.max_row + 1):
        number = ws.cell(row=row, column=header.section_col).value
        item = ws.cell(row=row, column=header.item_col).value if header.item_col else None
        article = ws.cell(row=row, column=header.article_col).value

        is_section = number is not None and TOP_LEVEL_RE.match(str(number).strip())
        # A row carrying neither a line number nor a section number is not
        # part of the priced work: it is something added underneath it. In the
        # offer this was written against, "Дополнительные работы" sits there
        # with 12.7 million against it, and skipping it would have left the
        # report 12.7 million short of the offer's own bottom line. The
        # "ИТОГО" rows below look the same but name themselves in the margin
        # rather than in a column this reads, so they fall out on their own.
        is_extra = started and number is None and item is None
        if not (is_section or is_extra):
            continue

        if not started:
            # An offer opens with a row for the lot itself: a section number,
            # no article, and the whole offer as its total. Sections start at
            # the first row that names an article, and anything above it is
            # that header — which must not be counted, or the report doubles.
            if not article:
                continue
            started = True

        # The column meant for the article name doesn't always hold one: one
        # offer numbers its articles there ("1", "1.1") and puts the wording
        # in the works column instead. A name has to have letters in it.
        name = _named(article) or _named(
            ws.cell(row=row, column=header.name_col).value if header.name_col else None
        )
        if not name:
            continue
        amount = ws.money_at(row, header.total_col)
        if amount is None:
            continue
        key = classify(name)
        if key is None:
            unmatched.append(str(name).strip())
            continue
        sections.append(Section(key, str(name).strip(), amount))

    return sections, unmatched


# --- quantity coefficients ("Расчётные коэффициенты бетонных и фасадных
# конструкций") --------------------------------------------------------------

# Unlike "Стоимость всего", this heading isn't spread across several columns
# under a merged parent — the cell just says so directly, wherever the
# header spans one row or two.
QTY_HEADER = "предлагаемое количество"

UNIT_HEADER_TOKENS = ("ед", "изм")


def _find_qty_column(ws, header_row):
    """The "Предлагаемое количество" column — the bidder's own proposed
    quantity for a line, as opposed to "Общее кол-во" (the customer's)."""
    for row in (header_row, header_row + 1):
        for col in range(1, HEADER_SEARCH_COLS + 1):
            if QTY_HEADER in _cell_text(ws, row, col):
                return col
    return None


def _find_unit_column(ws, header_row):
    for col in range(1, HEADER_SEARCH_COLS + 1):
        text = _cell_text(ws, header_row, col)
        if all(token in text for token in UNIT_HEADER_TOKENS):
            return col
    return None


def _is_volume_unit(text):
    """Whether a unit-of-measure cell reads as cubic metres — "м3" or "м³",
    with or without the space Excel sometimes leaves around it."""
    normalized = text.strip().lower().replace("³", "3").replace(" ", "")
    return normalized in ("м3", "m3")


def _is_area_unit(text):
    """Whether a unit-of-measure cell reads as square metres — "м2" or "м²"."""
    normalized = text.strip().lower().replace("²", "2").replace(" ", "")
    return normalized in ("м2", "m2")


def _quantity_by_category(path, category_key, is_matching_unit):
    """The proposed quantity summed under the top-level section(s) that
    classify as ``category_key``, restricted to lines whose own unit passes
    ``is_matching_unit``. Tried as an offer first ("Предлагаемое
    количество") and, failing that, as a levels estimate ("количество") —
    the same two shapes ``read_sections`` already reads cost from.

    Unlike cost, a quantity is never rolled up onto a section's own row —
    only the line items underneath it carry one — so this adds up every
    matching quantity between the section's row and the next top-level
    section, at any depth below it. Other kinds of work sometimes sit inside
    the same section (metalwork priced in tonnes inside "Возведение несущих
    конструкций", say), so a line only counts where its own unit matches.

    None where the workbook isn't laid out as either shape of sectioned
    estimate, has no quantity column, or has no section that classifies as
    ``category_key`` at all — as opposed to 0.0, which means the section is
    there but nothing under it matches.
    """
    path = Path(path)
    for ws in _checked_sheets(path):
        value = _quantity_by_category_from_sheet(ws, category_key, is_matching_unit)
        if value is None:
            # Не смета-оффер — попробовать как укрупнённую, с колонками
            # «номер N»/«уровень N» вместо одной колонки «№ раздела».
            value = _quantity_from_levels_sheet(ws, category_key, is_matching_unit, None)
        if value is not None:
            return value
    return None


def _quantity_from_levels_sheet(ws, category_key, is_matching_unit, name_contains):
    """The levels-estimate counterpart of ``_quantity_by_category_from_sheet``.

    Unlike an offer, a "укрупнённая смета" can state a quantity on a section
    or sub-section row itself as well as on the leaves underneath it — the
    same "own figure, or the sum of its parts" shape ``_sections_from_levels``
    already reads cost with. Summing every row regardless of level double- or
    triple-counts wherever a rollup row states its own quantity on top of its
    own breakdown: on the real sample this was written against, 159 342 m3
    instead of the 39 835 m3 the section states on its own row.
    """
    header = _find_levels_header(ws)
    if header is None or header.qty_col is None:
        return None

    def own_qty(row, name):
        if name_contains is not None and (name is None or name_contains not in name.lower()):
            return None
        qty = ws.amount_at(row, header.qty_col)
        if qty is None:
            return None
        if header.unit_col and not is_matching_unit(_cell_text(ws, row, header.unit_col)):
            return None
        return qty

    matched = False
    in_section = False
    section_own = None
    section_parts = 0.0
    sub_open = False
    sub_own = None
    sub_parts = 0.0

    def close_subsection():
        nonlocal section_parts, sub_open, sub_own, sub_parts
        if sub_open:
            section_parts += sub_own if sub_own is not None else sub_parts
        sub_open, sub_own, sub_parts = False, None, 0.0

    def close_section():
        nonlocal section_own, section_parts
        close_subsection()
        result = section_own if section_own is not None else section_parts
        section_own, section_parts = None, 0.0
        return result

    total = None
    for row in range(header.row + 1, ws.max_row + 1):
        first = _named(ws.cell(row=row, column=header.first).value)
        if first:
            if in_section:
                total = close_section()
            in_section = classify(first) == category_key
            matched = matched or in_section
            if in_section:
                section_own = own_qty(row, first)
            continue
        if not in_section:
            continue
        second = _named(ws.cell(row=row, column=header.second).value)
        if second:
            close_subsection()
            sub_own = own_qty(row, second)
            sub_open = True
            continue
        third = _named(ws.cell(row=row, column=header.third).value) if header.third else None
        qty = own_qty(row, third)
        if qty is None:
            continue
        if sub_open:
            sub_parts += qty
        else:
            section_parts += qty

    if in_section:
        total = close_section()

    return total if matched else None


def _section_row_ranges(ws, header, category_key):
    """(start row, end row) for every top-level section under this header
    that classifies as ``category_key`` — the section's own row and the row
    just before the next top-level section (or past the sheet's end for the
    last one). A list rather than a single pair: an estimate can carry more
    than one top-level section for the same report line.
    """
    section_rows = []
    for row in range(header.row + 2, ws.max_row + 1):
        number = ws.cell(row=row, column=header.section_col).value
        if number is None or not TOP_LEVEL_RE.match(str(number).strip()):
            continue
        name = _named(ws.cell(row=row, column=header.article_col).value) or _named(
            ws.cell(row=row, column=header.name_col).value if header.name_col else None
        )
        section_rows.append((row, name))

    ranges = []
    for i, (row, name) in enumerate(section_rows):
        if classify(name) != category_key:
            continue
        end = section_rows[i + 1][0] if i + 1 < len(section_rows) else ws.max_row + 1
        ranges.append((row, end))
    return ranges


# A numbered row at any depth ("6", "6.3", "6.3.3", ...) — a section or
# sub-section of its own, as opposed to a leaf line item, which carries no
# number in this column at all.
_NUMBERED_ROW_RE = re.compile(r"^\d+(\.\d+)*$")


def _quantity_by_category_from_sheet(ws, category_key, is_matching_unit):
    header = _find_header(ws)
    if header is None:
        return None
    qty_col = _find_qty_column(ws, header.row)
    if qty_col is None:
        return None
    unit_col = _find_unit_column(ws, header.row)

    ranges = _section_row_ranges(ws, header, category_key)
    if not ranges:
        return None

    total = 0.0
    for row, end in ranges:
        for r in range(row + 1, end):
            qty = ws.amount_at(r, qty_col)
            if qty is None:
                continue
            if unit_col and not is_matching_unit(_cell_text(ws, r, unit_col)):
                continue
            total += qty

    return total


def read_concrete_volume(path):
    """The proposed volume of monolithic concrete, in m³ — the "Предлагаемое
    количество" under the estimate's "Возведение несущих конструкций здания"
    section, the same section whose cost is the report's "concrete" line."""
    return _quantity_by_category(path, "concrete", _is_volume_unit)


# The facade classifier's own axis (column "Статья СМР") — the one place
# formulations agree word for word between estimates, unlike the free-text
# works name a person types by hand. Each facade type prices its own area
# on exactly one classifier position; its neighbours in the same type price
# a different layer at the same square metres (substructure, insulation,
# frame) and must not be added to it. Matched by the numeric code when an
# estimate states it, and by the position's own wording otherwise.
#
#   Тип фасада                     Площадь несёт              Не сюда (тот же тип)
#   Светопрозрачные (6.1, 6.2)     6.1.2/6.2.2 заполнение      6.1.1/6.2.1 профильная система
#   Навесной (6.3, 6.4)            6.3.3/6.4.3 облицовка       6.3.1/6.4.1 подсистема, .2 утеплитель
#   Модульный (6.5)                6.5.2 заполнение модуля     6.5.1 кронштейны, 6.5.3 прочее
#   Мокрый (6.7)                   6.7.2 штукатурка по сетке   6.7.1 утеплитель, 6.7.3 окраска
#   Реставрация (6.8, 6.9)         6.8.4 / 6.9.3 воссоздание   демонтаж, кладка, декор, навесы
#
# "профильная система" alone is deliberately not matched: bare, it's the
# translucent type's own excluded frame layer (6.1.1/6.2.1); only paired
# with "заполнение модуля" does it name the modular type's area, and that
# combination is already covered by the modular phrase below on its own.
FACADE_AREA_CODE_RE = re.compile(r"\b6\.(1\.2|2\.2|3\.3|4\.3|5\.2|7\.2|8\.4|9\.3)\b")
FACADE_AREA_PHRASES = (
    "устройство заполнения",
    "устройство облицовки",
    "заполнение модуля",
    "декоративная штукатурка",
    "воссоздание штукатурного фасада",
)


def _names_facade_area(article_text):
    text = (article_text or "").strip().lower()
    if not text:
        return False
    if FACADE_AREA_CODE_RE.search(text):
        return True
    if "воссоздание" in text and ("светопрозрачн" in text or "остеклен" in text):
        return True
    return any(phrase in text for phrase in FACADE_AREA_PHRASES)


def _facade_area_by_article(ws, header, ranges):
    """The facade area from rows whose "Статья СМР" names an
    area-bearing layer (``_names_facade_area``), or None if the article
    column names one nowhere in the section — asking to be filled in by
    hand rather than guessed at from a free-text works name that means
    something different in every estimate.

    A row that is itself numbered (a section or sub-section, not a leaf)
    is preferred over its own leaves: where the classifier is filled, it
    is usually filled on the свод, which then already states the figure
    whole rather than as parts still to be summed and at risk of double
    counting a rollup against its own breakdown.
    """
    if header.article_col is None:
        return None
    qty_col = _find_qty_column(ws, header.row)
    if qty_col is None:
        return None
    unit_col = _find_unit_column(ws, header.row)

    rollup_total = 0.0
    rollup_matched = False
    leaf_total = 0.0
    leaf_matched = False
    for start, end in ranges:
        for r in range(start + 1, end):
            if not _names_facade_area(_cell_text(ws, r, header.article_col)):
                continue
            qty = ws.amount_at(r, qty_col)
            if qty is None:
                continue
            if unit_col and not _is_area_unit(_cell_text(ws, r, unit_col)):
                continue
            number = ws.cell(row=r, column=header.section_col).value
            is_rollup = number is not None and _NUMBERED_ROW_RE.match(str(number).strip())
            if is_rollup:
                rollup_total += qty
                rollup_matched = True
            else:
                leaf_total += qty
                leaf_matched = True

    if rollup_matched:
        return rollup_total
    if leaf_matched:
        return leaf_total
    return None


def read_facade_area(path):
    """The proposed facade area, in m² — read from the "Статья СМР"
    classifier column under the estimate's facade section (any section
    whose name carries "фасад"), the same section whose cost is the
    report's "facade" line. See ``_facade_area_by_article`` and the map
    above it for how a row is told to carry the area or not.

    None where the classifier names no area-bearing layer anywhere in the
    section: a free-text works name is a person's own wording and not a
    safe basis to guess a layer from — the facade area field on the
    passport exists precisely for this case, to be filled in by hand.

    The levels-estimate shape ("укрупнённая смета") carries no "Статья
    СМР" column of its own; its facade section is still read by summing
    every square-metre leaf under it, the same as before.
    """
    path = Path(path)
    for ws in _checked_sheets(path):
        header = _find_header(ws)
        if header is not None:
            ranges = _section_row_ranges(ws, header, "facade")
            value = _facade_area_by_article(ws, header, ranges) if ranges else None
        else:
            value = None
        if value is None:
            value = _quantity_from_levels_sheet(
                ws, "facade", _is_area_unit, name_contains="панел",
            )
        if value is not None:
            return value
    return None
