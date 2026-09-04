import io
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app import predicted_increase


def _workbook(rows, *, header_row=1, amount_header="Предполагаемое ДС", total=None):
    """A workbook shaped like the real predicted-increase file: a row-number
    column, a name column, and an amount column headed with a word starting
    "предпол" — matching both the correct spelling and the typo actually
    seen in the field ("предпологаемое")."""
    wb = Workbook()
    ws = wb.active
    ws.cell(row=header_row, column=1, value="№")
    ws.cell(row=header_row, column=2, value="Стоимость по видам работ/расход:")
    ws.cell(row=header_row, column=3, value=amount_header)

    for offset, (name, amount) in enumerate(rows):
        row = header_row + 1 + offset
        ws.cell(row=row, column=1, value=offset + 1)
        ws.cell(row=row, column=2, value=name)
        ws.cell(row=row, column=3, value=amount)

    if total is not None:
        row = header_row + 2 + len(rows)
        ws.cell(row=row, column=2, value="Итого СМР, руб. с НДС с 20%")
        ws.cell(row=row, column=3, value=total)
    return wb


def _report(rows, **kwargs):
    buf = io.BytesIO()
    _workbook(rows, **kwargs).save(buf)
    buf.seek(0)
    return predicted_increase.read_report(buf)


def _by_key(report):
    return {row.key: row for row in report.rows}


# --- reading the file -------------------------------------------------------

def test_reads_the_sections_of_a_real_file():
    report = _report([
        ("Подготовительные работы и содержание площадки", 69398698),
        ("Устройство котлована", 3807232),
        ("Гидроизоляция подземной части", 32271746),
        ("Ж/Б конструкции", 97736329),
        ("Фасад", 7753581),
        ("Отделка МОП, двери, ворота", 419964716),
        ("Лифты", 26442511),
        ("Инженерные системы", 246462190),
        ("Благоустройство", 335105941),
        ("Технологические решения", 29316868),
        ("SHELL & CORE", 53089399),
        ("MR Base", 35726191),
    ])
    rows = _by_key(report)

    assert report.unmatched == []
    assert set(rows) == {
        "preparation", "excavation", "waterproofing", "concrete", "facade",
        "finishing", "lifts", "utilities", "landscaping", "technology",
        "shell_core", "mr_base",
    }
    assert rows["concrete"].label == "Монолит + МК"
    assert rows["concrete"].amount == Decimal("97736329")
    assert rows["concrete"].sources == ["Ж/Б конструкции"]


def test_detects_the_real_typo_in_the_header():
    # The field's actual file spells it "Предпологаемое ДС" — a transposed
    # "ло" for "ла" — and the reader has to find the column anyway.
    report = _report([("Фасад", 100)], amount_header="Предпологаемое ДС")

    assert report.total.amount == Decimal("100")


def test_a_metal_structures_row_also_lands_on_concrete():
    # "concrete" is labelled "Монолит + МК" — Ж/Б (monolith) and metal
    # structures both belong there.
    report = _report([("Металлические конструкции", 50), ("Ж/Б конструкции", 100)])
    rows = _by_key(report)

    assert rows["concrete"].amount == Decimal("150")
    assert set(rows["concrete"].sources) == {"Металлические конструкции", "Ж/Б конструкции"}


def test_an_unrecognized_kind_of_work_is_reported_as_unmatched():
    report = _report([("Совершенно новый вид работ", 100), ("Фасад", 50)])

    assert report.unmatched == ["Совершенно новый вид работ"]
    assert set(_by_key(report)) == {"facade"}


def test_a_row_with_no_amount_is_skipped():
    report = _report([("Фасад", None), ("Кровли", 100)])

    assert set(_by_key(report)) == {"roof"}


def test_the_workbooks_own_total_row_is_read_past_not_through():
    report = _report([("Фасад", 100), ("Кровли", 200)], total=300)

    assert report.total.amount == Decimal("300")
    assert set(_by_key(report)) == {"facade", "roof"}


def test_the_total_sums_exactly_not_with_a_floats_rounding_drift():
    # 100000.10 + 200000.20 + 300000.05 drifts under float addition; read as
    # Decimal (see predicted_increase._amount), it doesn't.
    report = _report([
        ("Фасад", 100000.10), ("Кровли", 200000.20), ("Лифты", 300000.05),
    ])

    assert report.total.amount == Decimal("600000.35")


def test_a_zero_amount_row_is_dropped_from_the_report():
    # A category priced at nothing everywhere has nothing to show — same
    # rule cost_increase applies to a line that is baseline 0 / current 0.
    report = _report([("Фасад", 0)])

    assert report.rows == []


# --- errors ------------------------------------------------------------------

def test_a_file_with_no_recognizable_header_is_rejected():
    wb = Workbook()
    wb.active.append(["Раздел", "Сумма"])
    wb.active.append(["Фасад", 100])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    with pytest.raises(predicted_increase.PredictedIncreaseError):
        predicted_increase.read_lines(buf)


def test_a_file_that_is_not_really_excel_is_rejected():
    with pytest.raises(predicted_increase.PredictedIncreaseError):
        predicted_increase.read_lines(io.BytesIO(b"this is not a real xlsx file"))
