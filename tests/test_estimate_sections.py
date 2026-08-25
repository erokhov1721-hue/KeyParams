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


# --- смета, написанная уровнями («укрупнённая смета») ---

def _levels_estimate(rows, *, header_row=3):
    """A workbook shaped like the other kind of estimate: a column pair per
    level of nesting instead of one column of section numbers.

    ``rows`` are ``(level, number, name, total)`` with level 1, 2 or 3.
    """
    wb = Workbook()
    ws = wb.active
    ws.cell(row=1, column=5, value="Приложение № 2 к Договору")
    ws.cell(row=header_row, column=2, value="номер 1")
    ws.cell(row=header_row, column=3, value="уровень 1")
    ws.cell(row=header_row, column=4, value="номер 2")
    ws.cell(row=header_row, column=5, value="уровень 2")
    ws.cell(row=header_row, column=6, value="номер 3")
    ws.cell(row=header_row, column=7, value="уровень 3")
    ws.cell(row=header_row, column=8, value="Ед. изм.")
    ws.cell(row=header_row, column=13, value="Всего, \nруб. \nс учетом НДС")

    for offset, (level, number, name, total) in enumerate(rows):
        row = header_row + 1 + offset
        number_col = {1: 2, 2: 4, 3: 6}[level]
        ws.cell(row=row, column=number_col, value=number)
        ws.cell(row=row, column=number_col + 1, value=name)
        if total is not None:
            ws.cell(row=row, column=13, value=total)
    return wb


def test_a_levels_estimate_sums_the_parts_of_each_section(tmp_path):
    # A section's own cell is empty and the money sits underneath it.
    path = _save(_levels_estimate([
        (1, 1, "Подготовительные работы, содержание площадки", None),
        (2, "1.1.", "Мобилизация площадки", 100.0),
        (2, "1.2.", "Содержание площадки", 200.0),
        (1, 2, "Котлован", None),
        (2, "2.1.", "Разработка грунта", 50.0),
    ]), tmp_path, "levels.xlsx")

    totals = estimate_sections.read_section_totals(path)

    assert totals == {"preparation": 300.0, "excavation": 50.0}


def test_a_levels_estimate_goes_a_level_deeper_when_it_has_to(tmp_path):
    # The sub-section is empty in its turn and its parts carry the money;
    # counting both would double the section.
    path = _save(_levels_estimate([
        (1, 4, "Конструктивные решения", None),
        (2, "4.1.", "Подземная часть", None),
        (3, "4.1.1.", "Фундаментная плита", 70.0),
        (3, "4.1.2.", "Горизонтальные конструкции", 30.0),
        (2, "4.2.", "Надземная часть", 400.0),
        (3, "4.2.1.", "Эта часть уже посчитана выше", 999.0),
    ]), tmp_path, "levels.xlsx")

    totals = estimate_sections.read_section_totals(path)

    assert totals == {"concrete": 500.0}


def test_a_levels_section_that_states_its_own_total_is_taken_at_its_word(tmp_path):
    path = _save(_levels_estimate([
        (1, 15, "Разработка рабочей документации", 278.0),
    ]), tmp_path, "levels.xlsx")

    assert estimate_sections.read_section_totals(path) == {"rd": 278.0}


def test_two_levels_sections_on_one_report_line_are_added_up(tmp_path):
    # "ВИС - механические системы" and "ВИС - электрические системы" are both
    # the report's utilities line.
    path = _save(_levels_estimate([
        (1, 10, "ВИС - механические системы", None),
        (2, "10.1.", "Отопление", 100.0),
        (1, 11, "ВИС - Электрические и слаботочные системы", None),
        (2, "11.1.", "Освещение", 200.0),
    ]), tmp_path, "levels.xlsx")

    assert estimate_sections.read_section_totals(path) == {"utilities": 300.0}


# --- разбор шапки в разных написаниях ---

def test_the_totals_column_is_found_even_when_its_heading_is_not_merged(tmp_path):
    # One offer leaves "Стоимость всего" unmerged; insisting on the merge left
    # it without a totals column and so without any sections at all.
    wb = _offer([(1, 1, "1. Котлован", "Котлован", 200.0)], header_row=1)
    ws = wb.active
    ws.unmerge_cells(start_row=1, start_column=9, end_row=1, end_column=12)
    path = _save(wb, tmp_path, "unmerged.xlsx")

    assert estimate_sections.read_section_totals(path) == {"excavation": 200.0}


def test_the_article_column_is_recognised_however_it_is_headed(tmp_path):
    wb = _offer([(1, 1, "1. Котлован", "Котлован", 200.0)])
    wb.active.cell(row=9, column=3, value="Справочник статей СМР")
    path = _save(wb, tmp_path, "spravochnik.xlsx")

    assert estimate_sections.read_section_totals(path) == {"excavation": 200.0}


def test_a_section_numbered_rather_than_named_is_read_from_the_works_column(tmp_path):
    # One offer numbers its articles ("1", "1.1") and puts the wording in the
    # works column instead.
    path = _save(_offer([
        (1, 1, "1", "Устройство котлована", 200.0),
    ]), tmp_path, "numbered.xlsx")

    assert estimate_sections.read_section_totals(path) == {"excavation": 200.0}


def test_the_wordings_of_four_real_estimates_are_all_recognised():
    cases = {
        "Возведение несущих конструкций здания (22-341-П-КР)": "concrete",
        "Отделка паркинга, технических помещений, МОП, двери, ворота": "finishing",
        "ВИС - механические системы": "utilities",
        "ВИС - Электрические и слаботочные системы": "utilities",
        "отделка квартир": "mr_base",
        "ПРОЕКТИРОВАНИЕ": "rd",
        "Устройство фасадов": "facade",
        "Устройство кровли": "roof",
        "лифты, подъемники": "lifts",
        "Общестроительные работы - перегородки и стены": "partitions",
    }
    for name, expected in cases.items():
        assert estimate_sections.classify(name) == expected, name


# --- read_concrete_volume ---

def _offer_with_quantity(rows, *, header_row=9, qty_col=10, unit_col=7):
    """A workbook shaped like a real offer that also carries a "Предлагаемое
    количество" column — the header spans two rows, as it does for real, with
    the quantity heading on the second and the unit-of-measure on the first.

    ``rows`` are ``(section_no, article, works_name, qty, unit)`` tuples.
    """
    wb = Workbook()
    ws = wb.active
    ws.cell(row=header_row, column=1, value="№ п/п")
    ws.cell(row=header_row, column=2, value="№ раздела")
    ws.cell(row=header_row, column=3, value="Статья СМР")
    ws.cell(row=header_row, column=4, value="Наименование работ")
    ws.cell(row=header_row, column=unit_col, value="Ед. изм")
    ws.cell(row=header_row + 1, column=qty_col, value="Предлагаемое количество")
    ws.cell(row=header_row, column=12, value="Стоимость всего")
    ws.cell(row=header_row + 1, column=12, value="Всего")

    for offset, (section, article, works, qty, unit) in enumerate(rows):
        row = header_row + 2 + offset
        ws.cell(row=row, column=1, value=offset + 1)
        ws.cell(row=row, column=2, value=section)
        ws.cell(row=row, column=3, value=article)
        ws.cell(row=row, column=4, value=works)
        ws.cell(row=row, column=unit_col, value=unit)
        ws.cell(row=row, column=qty_col, value=qty)
        ws.cell(row=row, column=12, value=1)
    return wb


def test_concrete_volume_sums_the_leaf_quantities_under_the_section(tmp_path):
    # The section's own row and its sub-section headers never carry a
    # quantity in a real offer — only the priced line items underneath do.
    path = _save(_offer_with_quantity([
        (4, "4. Конструктивные решения", "Возведение несущих конструкций здания", None, "м3"),
        ("4.1", "4.1. Подземная часть", "Ж/Б конструкции подземной части", None, "м3"),
        (None, None, "Фундаментная плита", 100.0, "м3"),
        (None, None, "Плиты перекрытия", 50.5, "м3"),
        (5, "5. Общестроительные работы", "Перегородки и стены", None, "м3"),
        (None, None, "Перегородка типовая", 999.0, "м3"),
    ]), tmp_path)

    assert estimate_sections.read_concrete_volume(path) == 150.5


def test_concrete_volume_ignores_lines_measured_in_other_units(tmp_path):
    # Metalwork sometimes sits inside the same section, priced by the tonne
    # rather than the cubic metre — it must not inflate a concrete volume.
    path = _save(_offer_with_quantity([
        (4, "4. Конструктивные решения", "Возведение несущих конструкций здания", None, "м3"),
        (None, None, "Монолит", 200.0, "м3"),
        (None, None, "Металлоконструкции", 10.0, "т"),
    ]), tmp_path)

    assert estimate_sections.read_concrete_volume(path) == 200.0


def test_concrete_volume_is_none_without_a_matching_section(tmp_path):
    path = _save(_offer_with_quantity([
        (1, "1. Котлован", "Устройство котлована", 50.0, "м3"),
    ]), tmp_path)

    assert estimate_sections.read_concrete_volume(path) is None


def test_concrete_volume_is_none_without_a_quantity_column(tmp_path):
    # The plain offer fixture has no "Предлагаемое количество" heading at all.
    path = _save(_offer([
        (1, 4, "4. Конструктивные решения", "Возведение несущих конструкций здания", 200.0),
    ]), tmp_path)

    assert estimate_sections.read_concrete_volume(path) is None


def test_concrete_volume_of_an_unreadable_file_is_reported_rather_than_crashing(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not a workbook at all")

    try:
        estimate_sections.read_concrete_volume(path)
    except estimate_sections.EstimateSectionsError:
        pass
    else:
        raise AssertionError("нечитаемый файл должен быть отклонён понятной ошибкой")


# --- read_facade_area ---

def test_facade_area_sums_the_panel_leaf_quantities_under_the_section(tmp_path):
    path = _save(_offer_with_quantity([
        (6, "6. Фасады", "Устройство фасадов", None, "м2"),
        (None, None, "Панель фасадная типовая", 5000.0, "м2"),
        (None, None, "Панель угловая", 1200.5, "м2"),
        (7, "7. Кровля", "Устройство кровли", None, "м2"),
        (None, None, "Панель кровельная", 999.0, "м2"),
    ]), tmp_path)

    assert estimate_sections.read_facade_area(path) == 6200.5


def test_facade_area_recognises_facade_named_with_any_of_its_wordings(tmp_path):
    # "фасад", "фасадные", "фасадов" — the classify() rule matches the
    # substring, so any of these must be found the same way.
    for name in ("Фасадные работы", "Устройство фасадов", "Фасад здания"):
        path = _save(_offer_with_quantity([
            (6, "6. " + name, name, None, "м2"),
            (None, None, "Панель фасадная", 100.0, "м2"),
        ]), tmp_path, name="facade.xlsx")
        assert estimate_sections.read_facade_area(path) == 100.0, name


def test_facade_area_ignores_lines_measured_in_other_units(tmp_path):
    path = _save(_offer_with_quantity([
        (6, "6. Фасады", "Устройство фасадов", None, "м2"),
        (None, None, "Панель навесная", 300.0, "м2"),
        (None, None, "Кронштейны", 50.0, "шт"),
    ]), tmp_path)

    assert estimate_sections.read_facade_area(path) == 300.0


def test_facade_area_ignores_the_substructure_and_insulation_layers(tmp_path):
    # A ventilated facade quotes the same square metres three times over —
    # once for the substructure, once for the insulation, once for the
    # cladding panels that finish it. Only the panels stand for the area;
    # counting all three would triple it.
    path = _save(_offer_with_quantity([
        (6, "6. Фасады", "Устройство навесного фасада", None, "м2"),
        (None, None, "Подсистема", 1000.0, "м2"),
        (None, None, "Утеплитель", 1000.0, "м2"),
        (None, None, "Панель из стеклофибробетона", 1000.0, "м2"),
    ]), tmp_path)

    assert estimate_sections.read_facade_area(path) == 1000.0


def test_facade_area_ignores_glazing_in_the_same_section(tmp_path):
    # Light-transmitting structures share the facade section but are a
    # different kind of facade entirely, and carry no "панель" line of
    # their own — no special-case is needed to keep them out.
    path = _save(_offer_with_quantity([
        (6, "6. Фасады", "Устройство фасадов", None, "м2"),
        (None, None, "Витражное остекление", 1200.5, "м2"),
        (None, None, "Панель фасадная", 300.0, "м2"),
    ]), tmp_path)

    assert estimate_sections.read_facade_area(path) == 300.0


def test_facade_area_is_none_without_a_matching_section(tmp_path):
    path = _save(_offer_with_quantity([
        (1, "1. Котлован", "Устройство котлована", 50.0, "м3"),
    ]), tmp_path)

    assert estimate_sections.read_facade_area(path) is None


def test_facade_area_of_an_unreadable_file_is_reported_rather_than_crashing(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not a workbook at all")

    try:
        estimate_sections.read_facade_area(path)
    except estimate_sections.EstimateSectionsError:
        pass
    else:
        raise AssertionError("нечитаемый файл должен быть отклонён понятной ошибкой")
