import pytest
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from app import estimate


def _save(tmp_path, wb, filename="smeta.xlsx"):
    path = tmp_path / filename
    wb.save(path)
    return path


def test_read_estimate_simple_values(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Раздел", "Кол-во", "Цена"])
    ws.append(["Земляные работы", 10, 1500.5])
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)

    assert len(sheets) == 1
    rows = sheets[0]["rows"]
    assert [c["value"] for c in rows[0]] == ["Раздел", "Кол-во", "Цена"]
    assert [c["value"] for c in rows[1]] == ["Земляные работы", "10", "1 500.50"]


def test_read_estimate_merged_cells_collapse_into_one(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Заголовок"
    ws.merge_cells("A1:C1")
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)

    row = sheets[0]["rows"][0]
    assert len(row) == 1
    assert row[0]["value"] == "Заголовок"
    assert row[0]["colspan"] == 3
    assert row[0]["rowspan"] == 1


def test_read_estimate_multiple_sheets_in_order(tmp_path):
    wb = Workbook()
    wb.active.title = "Смета"
    wb.create_sheet("Материалы")
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)

    assert [s["name"] for s in sheets] == ["Смета", "Материалы"]


def test_read_estimate_skips_hidden_sheet(tmp_path):
    wb = Workbook()
    wb.active.title = "Видимый"
    hidden = wb.create_sheet("Скрытый")
    hidden.sheet_state = "hidden"
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)

    assert [s["name"] for s in sheets] == ["Видимый"]


def test_read_estimate_formula_cell_never_shows_raw_formula_text(tmp_path):
    """openpyxl never evaluates formulas — a workbook it just created has no
    cached value for a formula cell, so it must render blank rather than
    leaking the raw "=..." text. (A real Excel-saved file *does* carry a
    cached value, which openpyxl's own data_only mode is trusted to read —
    that part isn't ours to re-test.)"""
    wb = Workbook()
    ws = wb.active
    ws["A1"] = 10
    ws["A2"] = "=A1*2"
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)

    assert sheets[0]["rows"][1][0]["value"] == ""


def test_read_estimate_captures_basic_formatting(tmp_path):
    wb = Workbook()
    ws = wb.active
    cell = ws["A1"]
    cell.value = "Итого"
    cell.font = Font(bold=True, italic=True)
    cell.fill = PatternFill(fill_type="solid", fgColor="FFFF0000")
    cell.alignment = Alignment(horizontal="center")
    cell.border = Border(top=Side(style="thin"), bottom=Side(style="thin"))
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)
    rendered = sheets[0]["rows"][0][0]

    assert rendered["value"] == "Итого"
    assert rendered["bold"] is True
    assert rendered["italic"] is True
    assert rendered["bg"] == "#FF0000"
    assert rendered["align"] == "center"
    assert rendered["border_top"] is True
    assert rendered["border_bottom"] is True
    assert rendered["border_left"] is False


def test_read_estimate_reports_column_widths(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "x"
    ws["B1"] = "y"
    ws.column_dimensions["B"].width = 40
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)
    widths = sheets[0]["col_widths"]

    assert len(widths) == 2
    assert widths[1] == 40


def test_read_estimate_raises_on_corrupted_file(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not a real xlsx file")

    with pytest.raises(estimate.EstimateReadError):
        estimate.read_estimate(path)
