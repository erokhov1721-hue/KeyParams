import zipfile
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

from .passport import format_number

DEFAULT_COLUMN_WIDTH = 8.43  # Excel's own default column width, in characters.
_ALIGNMENT_MAP = {
    "left": "left",
    "right": "right",
    "center": "center",
    "centerContinuous": "center",
}


class EstimateReadError(Exception):
    pass


def read_estimate(path) -> list:
    """Parse an .xlsx workbook into a list of rendered sheets.

    Each sheet is ``{"name": str, "rows": [[cell, ...], ...], "col_widths":
    [float, ...]}``. Hidden and very-hidden sheets are skipped. A cell
    covered by a merge (other than the merge's top-left cell) is omitted
    from its row — the top-left cell instead carries the merge's rowspan
    and colspan.
    """
    path = Path(path)
    try:
        wb_styles = openpyxl.load_workbook(path, data_only=False)
        wb_values = openpyxl.load_workbook(path, data_only=True)
    except (zipfile.BadZipFile, KeyError, InvalidFileException, ValueError) as e:
        raise EstimateReadError(f"Cannot read {path}: {e}") from e

    sheets = []
    for ws_styles in wb_styles.worksheets:
        if ws_styles.sheet_state != "visible":
            continue
        sheets.append(_render_sheet(ws_styles, wb_values[ws_styles.title]))
    return sheets


def _render_sheet(ws_styles, ws_values):
    max_row = ws_styles.max_row or 0
    max_col = ws_styles.max_column or 0
    span, covered = _merge_spans(ws_styles)

    rows = []
    for r in range(1, max_row + 1):
        row_cells = []
        for c in range(1, max_col + 1):
            if (r, c) in covered:
                continue
            rowspan, colspan = span.get((r, c), (1, 1))
            row_cells.append(_render_cell(
                ws_styles.cell(row=r, column=c),
                ws_values.cell(row=r, column=c),
                rowspan, colspan,
            ))
        rows.append(row_cells)

    col_widths = []
    for c in range(1, max_col + 1):
        dim = ws_styles.column_dimensions.get(get_column_letter(c))
        col_widths.append(dim.width if dim and dim.width else DEFAULT_COLUMN_WIDTH)

    return {"name": ws_styles.title, "rows": rows, "col_widths": col_widths}


def _merge_spans(ws):
    """(span, covered): ``span`` maps a merge's top-left ``(row, col)`` to
    ``(rowspan, colspan)``; ``covered`` holds every other ``(row, col)``
    inside a merged range, which must be skipped when laying out a row."""
    span = {}
    covered = set()
    for merged_range in ws.merged_cells.ranges:
        top_left = (merged_range.min_row, merged_range.min_col)
        span[top_left] = (
            merged_range.max_row - merged_range.min_row + 1,
            merged_range.max_col - merged_range.min_col + 1,
        )
        for r in range(merged_range.min_row, merged_range.max_row + 1):
            for c in range(merged_range.min_col, merged_range.max_col + 1):
                if (r, c) != top_left:
                    covered.add((r, c))
    return span, covered


def _render_cell(cell_style, cell_value, rowspan, colspan):
    border = cell_style.border
    return {
        "value": _format_value(cell_value.value),
        "rowspan": rowspan,
        "colspan": colspan,
        "bold": bool(cell_style.font and cell_style.font.bold),
        "italic": bool(cell_style.font and cell_style.font.italic),
        "align": _alignment(cell_style.alignment),
        "bg": _fill_color(cell_style.fill),
        "border_top": _has_border(border.top),
        "border_right": _has_border(border.right),
        "border_bottom": _has_border(border.bottom),
        "border_left": _has_border(border.left),
    }


def _format_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, (int, float)):
        return format_number(value)
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y")
    return str(value)


def _alignment(alignment):
    if alignment is None or not alignment.horizontal:
        return None
    return _ALIGNMENT_MAP.get(alignment.horizontal)


def _fill_color(fill):
    if fill is None or fill.fill_type != "solid":
        return None
    fg = fill.fgColor
    if fg is None or fg.type != "rgb" or not fg.rgb:
        return None
    rgb = fg.rgb
    if not isinstance(rgb, str) or len(rgb) < 6:
        return None
    if len(rgb) == 8:  # AARRGGBB -> drop the alpha channel
        rgb = rgb[2:]
    return f"#{rgb}"


def _has_border(side):
    return bool(side and side.style)
