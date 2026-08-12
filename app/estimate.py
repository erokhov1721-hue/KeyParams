import zipfile
from pathlib import Path

import openpyxl
from openpyxl.styles.colors import COLOR_INDEX
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
# Default Office Open XML theme colors (used when workbook has no embedded theme)
_DEFAULT_THEME_COLORS = [
    "000000",  # 0: dark1 (black)
    "FFFFFF",  # 1: light1 (white)
    "E7E6E6",  # 2: dark2 (light gray)
    "C5C2C2",  # 3: light2 (gray)
    "4472C4",  # 4: accent1 (blue)
    "ED7D31",  # 5: accent2 (orange)
    "A5A5A5",  # 6: accent3 (gray)
    "FFC000",  # 7: accent4 (yellow)
    "5B9BD5",  # 8: accent5 (light blue)
    "70AD47",  # 9: accent6 (green)
]


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
        sheets.append(_render_sheet(ws_styles, wb_values[ws_styles.title], wb_styles))
    return sheets


def _render_sheet(ws_styles, ws_values, wb):
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
                wb,
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


def _render_cell(cell_style, cell_value, rowspan, colspan, wb):
    border = cell_style.border
    return {
        "value": _format_value(cell_value.value),
        "rowspan": rowspan,
        "colspan": colspan,
        "bold": bool(cell_style.font and cell_style.font.bold),
        "italic": bool(cell_style.font and cell_style.font.italic),
        "align": _alignment(cell_style.alignment),
        "bg": _fill_color(cell_style.fill, wb),
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


def _fill_color(fill, wb):
    if fill is None or fill.fill_type != "solid":
        return None
    fg = fill.fgColor
    if fg is None:
        return None

    # Handle RGB colors directly
    if fg.type == "rgb":
        try:
            rgb = fg.rgb
            if isinstance(rgb, str) and len(rgb) >= 6:
                if len(rgb) == 8:  # AARRGGBB -> drop the alpha channel
                    rgb = rgb[2:]
                return f"#{rgb}"
        except (AttributeError, ValueError):
            pass

    # Handle indexed colors from the standard palette
    if fg.type == "indexed":
        try:
            idx = fg.indexed
            if idx is not None and 0 <= idx < len(COLOR_INDEX):
                indexed_color = COLOR_INDEX[idx]
                if isinstance(indexed_color, str) and len(indexed_color) >= 6:
                    if len(indexed_color) == 8:
                        indexed_color = indexed_color[2:]
                    return f"#{indexed_color}"
        except (AttributeError, IndexError, TypeError):
            pass

    # Handle theme colors using the standard Office default theme colors.
    # Note: This uses an approximation (standard Office theme palette) rather than
    # attempting to parse the workbook's embedded theme XML. This is a known
    # limitation that provides reasonable color approximations for most estimates
    # while keeping the code simple and avoiding brittle XML parsing.
    if fg.type == "theme":
        try:
            theme_idx = fg.theme
            if theme_idx is not None and 0 <= theme_idx < len(_DEFAULT_THEME_COLORS):
                rgb = _DEFAULT_THEME_COLORS[theme_idx]
                if len(rgb) >= 6:
                    return f"#{rgb}"
        except (AttributeError, IndexError, TypeError):
            pass  # Theme resolution failed, return None

    return None


def _has_border(side):
    return bool(side and side.style)
