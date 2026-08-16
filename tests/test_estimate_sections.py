from openpyxl import Workbook

from app import estimate_sections


def _offer(rows, *, header_row=9):
    """A workbook shaped like a real tender offer.

    ``rows`` are ``(item_no, section_no, article, works_name, total)`` tuples,
    written below a two-storey header: "Стоимость всего" spans four columns
    with "Всего" as the last of them, and the per-unit prices above sit under
    an identically-shaped heading of their own — which is what makes finding
    the right "Всего" the interesting part.
    """
    wb = Workbook()
    ws = wb.active
    ws.cell(row=2, column=1, value="Предмет тендера:")

    ws.cell(row=header_row, column=1, value="№ п/п")
    ws.cell(row=header_row, column=2, value="№ раздела")
    ws.cell(row=header_row, column=3, value="Статья СМР")
    ws.cell(row=header_row, column=4, value="Наименование работ")

    ws.cell(row=header_row, column=5, value="Цена за ед. изм., RUB, с учетом НДС 20%")
    ws.merge_cells(start_row=header_row, start_column=5, end_row=header_row, end_column=8)
    ws.cell(row=header_row, column=9, value="Стоимость всего, RUB, с учетом НДС 20%")
    ws.merge_cells(start_row=header_row, start_column=9, end_row=header_row, end_column=12)
    ws.cell(row=header_row, column=13, value="Стоимость всего за объемы заказчика")

    for col, title in ((5, "Материалы"), (6, "СМР"), (7, "Косвенные расходы"), (8, "Всего")):
        ws.cell(row=header_row + 1, column=col, value=title)
    for col, title in ((9, "Материалы"), (10, "СМР"), (11, "Косвенные расходы"), (12, "Всего")):
        ws.cell(row=header_row + 1, column=col, value=title)

    for offset, (item, section, article, works, total) in enumerate(rows):
        row = header_row + 2 + offset
        ws.cell(row=row, column=1, value=item)
        ws.cell(row=row, column=2, value=section)
        ws.cell(row=row, column=3, value=article)
        ws.cell(row=row, column=4, value=works)
        # A different number in the unit-price "Всего", so a reader that picks
        # the wrong column is caught rather than accidentally right.
        ws.cell(row=row, column=8, value=1)
        ws.cell(row=row, column=12, value=total)
    return wb


def _save(wb, tmp_path, name="smeta.xlsx"):
    path = tmp_path / name
    wb.save(path)
    return path


# --- classify ---

def test_classify_recognises_the_sections_of_a_real_offer():
    cases = {
        "1. Подготовительные работы, содержание площадки": "preparation",
        "2. Котлован": "excavation",
        "3. Устройство гидроизоляции подземной части": "waterproofing",
        "4. Конструктивные решения": "concrete",
        "5. Общестроительные работы (без отделки)": "partitions",
        "6. Фасадные работы": "facade",
        "7. Кровля": "roof",
        "8. Отделочные работы (паркинг, надземная часть МОП)": "finishing",
        "9. Лифты, подъемники": "lifts",
        "Инженерные системы": "utilities",
        "12. Благоустройство, дороги": "landscaping",
        "13. ТХ": "technology",
        "99. Прочее": "other",
        "14. MR-base": "mr_base",
        "16. Разработка рабочей документации": "rd",
        "Дополнительные работы": "other",
    }
    for name, expected in cases.items():
        assert estimate_sections.classify(name) == expected, name


def test_classify_ignores_a_leading_article_number():
    # The numbering is per-workbook and drifts; the name is what identifies
    # a section.
    assert estimate_sections.classify("12. Благоустройство") == "landscaping"
    assert estimate_sections.classify("Благоустройство") == "landscaping"


def test_classify_matches_a_short_name_as_a_whole_word():
    # "ТХ" is a section; the same two letters inside "отходов" are not.
    assert estimate_sections.classify("13. ТХ") == "technology"
    assert estimate_sections.classify("Вывоз отходов") is None


def test_classify_of_an_unknown_section_is_none():
    assert estimate_sections.classify("Содержание вертолётной площадки") is None
    assert estimate_sections.classify("") is None
    assert estimate_sections.classify(None) is None


# --- read_section_totals ---

def test_totals_are_read_per_section(tmp_path):
    path = _save(_offer([
        (1, 1, "1. Подготовительные работы", "Подготовка", 100.0),
        (2, None, None, "Ограждение", 40.0),
        (3, "1.1", "1.1. Мобилизация", "Мобилизация", 60.0),
        (4, 2, "2. Котлован", "Котлован", 200.0),
    ]), tmp_path)

    totals = estimate_sections.read_section_totals(path)

    # Only the top-level rows count: their sub-sections and line items are
    # already summed into them.
    assert totals == {"preparation": 100.0, "excavation": 200.0}


def test_the_lot_header_row_is_not_counted_as_a_section(tmp_path):
    # An offer opens with the lot itself: a section number, no article name,
    # and the whole offer as its total.
    path = _save(_offer([
        (1, 1, None, "Лот №1 - Генподряд", 999.0),
        (1, 1, "1. Котлован", "Котлован", 200.0),
    ]), tmp_path)

    totals = estimate_sections.read_section_totals(path)

    assert totals == {"excavation": 200.0}


def test_a_section_named_only_in_the_works_column_is_still_read(tmp_path):
    # Seen in a real offer: one section of fifteen had its "Статья СМР" left
    # blank, and dropping it would have lost 1.9 billion roubles.
    path = _save(_offer([
        (1, 1, "1. Котлован", "Котлован", 200.0),
        (2, 2, None, "Инженерные системы", 1908214707.4),
    ]), tmp_path)

    totals = estimate_sections.read_section_totals(path)

    assert totals["utilities"] == 1908214707.4


def test_a_section_that_costs_nothing_is_a_zero_not_a_gap(tmp_path):
    path = _save(_offer([
        (1, 1, "1. Котлован", "Котлован", 200.0),
        (2, 2, "12. Благоустройство", "Благоустройство", 0),
    ]), tmp_path)

    totals = estimate_sections.read_section_totals(path)

    assert totals["landscaping"] == 0.0


def test_an_unnumbered_addition_below_the_sections_is_counted(tmp_path):
    # "Дополнительные работы" carries neither a line number nor a section
    # number; skipping it left the report short of the offer's own total.
    path = _save(_offer([
        (1, 1, "1. Котлован", "Котлован", 200.0),
        (None, None, None, "Дополнительные работы", 12.5),
    ]), tmp_path)

    totals = estimate_sections.read_section_totals(path)

    assert totals == {"excavation": 200.0, "other": 12.5}


def test_the_closing_total_rows_are_not_counted(tmp_path):
    # "ИТОГО" names itself in the margin, outside the columns this reads, so
    # it never acquires a name and falls out.
    wb = _offer([
        (1, 1, "1. Котлован", "Котлован", 200.0),
    ])
    ws = wb.active
    ws.cell(row=12, column=1, value="ИТОГО, руб. с учетом НДС")
    ws.cell(row=12, column=12, value=200.0)
    path = _save(wb, tmp_path)

    totals = estimate_sections.read_section_totals(path)

    assert totals == {"excavation": 200.0}


def test_the_totals_column_is_the_one_under_the_total_cost_heading(tmp_path):
    # Both headings have a "Всего" beneath them; picking the unit-price one
    # would report 1 rouble per section.
    path = _save(_offer([
        (1, 1, "1. Котлован", "Котлован", 200.0),
    ]), tmp_path)

    assert estimate_sections.read_section_totals(path) == {"excavation": 200.0}


def test_sections_the_report_has_no_line_for_are_left_out(tmp_path):
    path = _save(_offer([
        (1, 1, "1. Котлован", "Котлован", 200.0),
        (2, 2, "2. Содержание вертолётной площадки", "Вертолёты", 50.0),
    ]), tmp_path)

    assert estimate_sections.read_section_totals(path) == {"excavation": 200.0}


def test_a_workbook_that_is_not_an_offer_yields_nothing(tmp_path):
    wb = Workbook()
    wb.active.append(["Раздел", "Сумма"])
    wb.active.append(["Фундамент", 1000])
    path = _save(wb, tmp_path)

    assert estimate_sections.read_section_totals(path) == {}


def test_an_unreadable_file_is_reported_rather_than_crashing(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not a workbook at all")

    try:
        estimate_sections.read_section_totals(path)
    except estimate_sections.EstimateSectionsError:
        pass
    else:
        raise AssertionError("нечитаемый файл должен быть отклонён понятной ошибкой")
