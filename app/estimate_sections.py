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
from pathlib import Path

import openpyxl

from . import extractors

logger = logging.getLogger(__name__)

# The report's cost lines, in the order they appear on the sheet, each with
# the words that identify its section in an estimate. First match wins, so
# order matters where names overlap: "Общестроительные работы (без отделки)"
# has to be claimed by the partitions line before the finishing line can see
# the word "отдел" in it.
CATEGORY_RULES = [
    ("rd", ("рабочей документации", "рабочая документация", "стадии \"р\"", "стадии р")),
    ("preparation", ("подготовительные работы", "содержание площадки")),
    ("excavation", ("котлован",)),
    ("waterproofing", ("гидроизоляц",)),
    ("concrete", ("конструктивные решения", "монолит")),
    ("partitions", ("общестроительные", "перегородк")),
    ("facade", ("фасад",)),
    ("roof", ("кровля", "кровли")),
    ("finishing", ("отделочные работы", "отделка")),
    ("lifts", ("лифт",)),
    ("utilities", ("инженерн",)),
    ("landscaping", ("благоустройств",)),
    ("technology", ("технологическ", "тх")),
    ("other", ("прочее", "зип", "другие", "дополнительные работы")),
    ("mr_base", ("mr-base", "mr base")),
    ("mr_ready", ("mr-ready", "mr ready")),
    ("shell_core", ("shell", "нулевого цикла", "нулевой цикл")),
]

CATEGORY_KEYS = [key for key, _ in CATEGORY_RULES]

# How far down to look for the header: an offer opens with the tender's name,
# the object, the address and the bidder's details before the table starts.
HEADER_SEARCH_ROWS = 40
HEADER_SEARCH_COLS = 40

SECTION_HEADER = "раздел"
ARTICLE_HEADER = "статья"
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


def _cell_text(ws, row, col):
    value = ws.cell(row=row, column=col).value
    return str(value).strip().lower() if value is not None else ""


def _horizontal_span(ws, row, col):
    for merged in ws.merged_cells.ranges:
        if merged.min_row == row and merged.min_col == col:
            return merged.min_col, merged.max_col
    return col, col


def _find_total_column(ws, header_row):
    """The column holding each section's total cost.

    An offer states costs twice over — per unit and in total — under merged
    headings with the same four sub-columns beneath each, so the heading alone
    doesn't identify a column. The total block is the one spanning several
    columns with a "Всего" underneath it; "Стоимость всего за объёмы
    заказчика" sits alongside as a single column with nothing under it, and is
    passed over for exactly that reason.
    """
    for col in range(1, HEADER_SEARCH_COLS + 1):
        if TOTAL_HEADER not in _cell_text(ws, header_row, col):
            continue
        first, last = _horizontal_span(ws, header_row, col)
        if last == first:
            continue
        for sub in range(first, last + 1):
            if _cell_text(ws, header_row + 1, sub) == TOTAL_SUBHEADER:
                return sub
    return None


Header = namedtuple(
    "Header", "row item_col section_col article_col name_col total_col",
)


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

    Returns an empty dict for a workbook that isn't laid out as a sectioned
    offer at all: the report then leaves its cost lines blank, exactly as it
    did before any estimate was attached.
    """
    path = Path(path)
    try:
        # Not read_only: the header spans merged cells, and a streaming
        # worksheet doesn't carry the merges needed to tell the two
        # cost blocks apart. Only three cells per row are read afterwards,
        # so the whole-workbook load is the cheaper half of this anyway.
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:
        raise EstimateSectionsError(f"Cannot read {path}: {e}") from e

    for ws in wb.worksheets:
        totals = _totals_from_sheet(ws)
        if totals:
            return totals
    return {}


def _totals_from_sheet(ws):
    header = _find_header(ws)
    if header is None:
        return {}

    totals = {}
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

        name = article or (
            ws.cell(row=row, column=header.name_col).value if header.name_col else None
        )
        if not name:
            continue
        amount = _amount(ws.cell(row=row, column=header.total_col).value)
        if amount is None:
            continue
        key = classify(name)
        if key is None:
            unmatched.append(str(name).strip())
            continue
        totals[key] = totals.get(key, 0.0) + amount

    if unmatched:
        # Not an error: an estimate may carry sections this report has no line
        # for. Logged so that a section quietly going missing can be traced.
        logger.info("Разделы сметы без строки в отчёте: %s", "; ".join(unmatched))
    return totals
