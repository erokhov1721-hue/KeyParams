import pytest

from app import extractors
from app.document_reader import DocxContent


# --- parse_number ---

def test_parse_number_thousands_separator():
    assert extractors.parse_number("9 489") == 9489.0


def test_parse_number_decimal_comma():
    assert extractors.parse_number("12 400,5") == 12400.5


def test_parse_number_dash_is_none():
    assert extractors.parse_number("-") is None


def test_parse_number_empty_is_none():
    assert extractors.parse_number("") is None
    assert extractors.parse_number(None) is None


# --- extract_general_contractor (synthetic) ---

def test_extract_general_contractor_synthetic():
    dgp = DocxContent(
        paragraphs=[
            "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
            "именуемое в дальнейшем «Генподрядчик», с третьей стороны,"
        ],
        tables=[],
    )
    assert extractors.extract_general_contractor(dgp) == "ООО «Ромашка»"


def test_extract_general_contractor_not_found():
    dgp = DocxContent(paragraphs=["Ничего релевантного здесь нет."], tables=[])
    assert extractors.extract_general_contractor(dgp) is None


# --- extract_contract_price (synthetic) ---

def test_extract_contract_price_found():
    dgp = DocxContent(
        paragraphs=[
            "Цена Работ, выполняемых Генподрядчиком по настоящему Договору "
            "(Цена Договора), составляет сумму 10 067 050 887,72 руб. "
            "(Десять миллиардов шестьдесят семь миллионов пятьдесят тысяч "
            "восемьсот восемьдесят семь рублей 72 копейки), в том числе НДС."
        ],
        tables=[],
    )
    assert extractors.extract_contract_price(dgp) == 10067050887.72


def test_extract_contract_price_not_found():
    dgp = DocxContent(paragraphs=["Ничего релевантного здесь нет."], tables=[])
    assert extractors.extract_contract_price(dgp) is None


# --- extract_signing_year (synthetic) ---

def test_extract_signing_year_found():
    dgp = DocxContent(
        paragraphs=["г. Москва", "«04» февраля 2025 г."],
        tables=[],
    )
    assert extractors.extract_signing_year(dgp) == "2025"


def test_extract_signing_year_not_found():
    dgp = DocxContent(paragraphs=["г. Москва", ""], tables=[])
    assert extractors.extract_signing_year(dgp) is None


def test_extract_signing_year_found_standalone_on_title_page():
    # No dated preamble at all — just a cover-page line with the year alone,
    # a common convention on Russian contract title pages.
    dgp = DocxContent(
        paragraphs=["ДОГОВОР ГЕНЕРАЛЬНОГО ПОДРЯДА", "", "2025 год"],
        tables=[],
    )
    assert extractors.extract_signing_year(dgp) == "2025"


def test_extract_signing_year_prefers_dated_preamble_over_standalone_line():
    # When both are present, the actual signing date (from the preamble)
    # is more precise than the cover-page year and should win.
    dgp = DocxContent(
        paragraphs=["2024 год", "г. Москва", "«04» февраля 2025 г."],
        tables=[],
    )
    assert extractors.extract_signing_year(dgp) == "2025"


def test_extract_signing_year_found_uppercase_city():
    # Contract letterheads sometimes render the preamble in all caps.
    dgp = DocxContent(
        paragraphs=["г. МОСКВА", "«04» февраля 2025 г."],
        tables=[],
    )
    assert extractors.extract_signing_year(dgp) == "2025"


# --- extract_building_class (synthetic) ---

def test_extract_building_class_found():
    dgp = DocxContent(paragraphs=["Жилой комплекс бизнес-класса."], tables=[])
    tz = DocxContent(paragraphs=[], tables=[])
    assert extractors.extract_building_class(dgp, tz) == "Бизнес"


def test_extract_building_class_found_in_table_cell():
    # Real ТЗ documents describe apartment finishing specs in a table, with
    # the class named as a quoted assignment: 'класса «Бизнес»'.
    dgp = DocxContent(paragraphs=[], tables=[])
    tz = DocxContent(
        paragraphs=[],
        tables=[[["Помещения квартир – коммерческое жилье класса «Бизнес»."]]],
    )
    assert extractors.extract_building_class(dgp, tz) == "Бизнес"


def test_extract_building_class_not_found():
    dgp = DocxContent(paragraphs=["Класс энергоэффективности лифта не ниже B."], tables=[])
    tz = DocxContent(paragraphs=[], tables=[])
    assert extractors.extract_building_class(dgp, tz) is None


def test_extract_building_class_ignores_enumeration():
    dgp = DocxContent(paragraphs=[], tables=[])
    tz = DocxContent(
        paragraphs=[
            "Стандарт умного жилого комплекса классы КОМФОРТ и БИЗНЕС, версия 5.0."
        ],
        tables=[],
    )
    assert extractors.extract_building_class(dgp, tz) is None


def test_extract_building_class_found_despite_unrelated_second_mention():
    # A genuine assignment ("бизнес-класса") sharing a paragraph with an
    # unrelated second class keyword ("премиум-класса", describing the
    # business center on the ground floor, not the residential complex)
    # must still be extracted correctly rather than being discarded as
    # if the whole paragraph were an enumeration.
    dgp = DocxContent(
        paragraphs=[
            "Жилой комплекс бизнес-класса, расположенный рядом с "
            "бизнес-центром премиум-класса на первом этаже."
        ],
        tables=[],
    )
    tz = DocxContent(paragraphs=[], tables=[])
    assert extractors.extract_building_class(dgp, tz) == "Бизнес"


# --- area extractors (synthetic) ---

def test_extract_underground_area_found():
    tz = DocxContent(
        paragraphs=[],
        tables=[[
            ["№", "Наименование", "Ед.изм", "Итого"],
            ["1", "Площадь подземной части", "м2", "1 000"],
        ]],
    )
    assert extractors.extract_underground_area(tz) == 1000.0


def test_extract_aboveground_area_found():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Площадь надземной части", "м2", "2 000"]]],
    )
    assert extractors.extract_aboveground_area(tz) == 2000.0


def test_extract_total_area_found():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Общая площадь комплекса", "м2", "3 000"]]],
    )
    assert extractors.extract_total_area(tz) == 3000.0


def test_extract_underground_area_ignores_floor_count_row():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Количество подземных этажей", "этаж", "2"]]],
    )
    assert extractors.extract_underground_area(tz) is None


def test_extract_total_area_takes_first_value_column():
    # "Итого / Корпус 1 / Корпус 2" breakdown: the value belonging to the
    # label is the one right after it, not the rightmost number in the row.
    tz = DocxContent(
        paragraphs=[],
        tables=[[
            ["№", "Наименование", "Ед.изм", "Итого", "Корпус 1", "Корпус 2"],
            ["1", "Общая площадь", "м2", "50000", "20000", "30000"],
        ]],
    )
    assert extractors.extract_total_area(tz) == 50000.0


def test_extract_underground_area_ignores_floor_count_row_with_area_column():
    # The row is about a floor *count*; the tokens "площад" and "подземн" only
    # both appear because an unrelated "Площадь застройки" column sits in the
    # same row. Joining the whole row into one label would return 999.
    tz = DocxContent(
        paragraphs=[],
        tables=[[
            ["1", "Количество подземных этажей", "этаж", "2", "Площадь застройки", "999"],
        ]],
    )
    assert extractors.extract_underground_area(tz) is None


def test_extract_area_skips_unit_cell_as_value():
    # "м2" must not be read as the number 2.
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Площадь надземной части", "м2", "2 000"]]],
    )
    assert extractors.extract_aboveground_area(tz) == 2000.0


@pytest.mark.parametrize("cell, expected", [
    ("50 000 м2", 50000.0),
    ("1 000 м2", 1000.0),
    ("12,5 м2", 12.5),
    ("1 000 кв.м", 1000.0),
    ("5 га", 5.0),
    ("1 000 м²", 1000.0),
    ("2 этажа", 2.0),
    ("5 шт.", 5.0),
    # No unit at all — unchanged behaviour.
    ("1 000", 1000.0),
    ("12 400,5", 12400.5),
    # Not values: a bare unit, a dash, and text (including text that starts
    # with a digit but carries an unrecognised unit).
    ("м2", None),
    ("-", None),
    ("Общая площадь", None),
    ("2 корпуса", None),
])
def test_numeric_cell_value_ignores_trailing_unit(cell, expected):
    """Only the numeric part of a cell is parsed; the unit is discarded.

    parse_number strips non-digit characters, so handing it the whole cell
    would append the unit's own digit to the value: "50 000 м2" parsed as a
    whole yields 500002, and "12,5 м2" yields 12.52.
    """
    assert extractors._numeric_cell_value(cell) == expected


def test_extract_area_value_cell_contains_number_and_unit():
    """A value cell holding "50 000 м2" must read as 50000, not 500002."""
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Общая площадь", "50 000 м2"]]],
    )
    assert extractors.extract_total_area(tz) == 50000.0


def test_extract_area_value_cell_with_unit_and_decimal():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Площадь подземной части", "12,5 м2"]]],
    )
    assert extractors.extract_underground_area(tz) == 12.5


def test_extract_area_label_split_across_two_cells():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["Площадь", "подземной части", "1 234"]]],
    )
    assert extractors.extract_underground_area(tz) == 1234.0


# --- real fixtures: documented expectations from the design spec ---

def test_real_general_contractor(real_dgp):
    assert extractors.extract_general_contractor(real_dgp) == "ООО «АНТТЕК»"


def test_real_contract_price(real_dgp):
    assert extractors.extract_contract_price(real_dgp) == 10067050887.72


def test_real_signing_year_found_on_title_page(real_dgp):
    # The real DGP has no dated preamble, but its cover page ends with a
    # standalone "2025 год" line, which is where the year actually comes from.
    assert extractors.extract_signing_year(real_dgp) == "2025"


def test_real_building_class_found_in_tz_table(real_dgp, real_tz):
    # The class isn't in any top-level paragraph — it's named inside a table
    # cell describing apartment finishing: 'класса «Бизнес»'.
    assert extractors.extract_building_class(real_dgp, real_tz) == "Бизнес"


def test_real_underground_area_not_present(real_tz):
    assert extractors.extract_underground_area(real_tz) is None


def test_real_aboveground_area_not_present(real_tz):
    assert extractors.extract_aboveground_area(real_tz) is None


def test_real_total_area_not_present(real_tz):
    assert extractors.extract_total_area(real_tz) is None


def test_extract_aboveground_area_accepts_nazemnaya_variant():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Общая наземная площадь", "м2", "54 116"]]],
    )
    assert extractors.extract_aboveground_area(tz) == 54116.0


def test_extract_total_area_ignores_subarea_rows():
    tz = DocxContent(
        paragraphs=[],
        tables=[[
            ["1", "Общая площадь подземного паркинга", "м2", "13 297"],
            ["2", "Общая наземная площадь", "м2", "54 116"],
            ["3", "Общая площадь", "м2", "67 413"],
        ]],
    )
    assert extractors.extract_total_area(tz) == 67413.0


def test_extract_total_area_ignores_footprint_row():
    # "Общая площадь застройки" (total building-footprint area) matches the
    # same tokens as the real complex total but is a distinct metric.
    tz = DocxContent(
        paragraphs=[],
        tables=[[
            ["1", "Общая площадь застройки", "м2", "12 000"],
            ["2", "Общая площадь", "м2", "67 413"],
        ]],
    )
    assert extractors.extract_total_area(tz) == 67413.0


def test_extract_underground_area_ignores_footprint_row():
    # "Площадь застройки подземной части" (building-footprint area) is a
    # distinct, named metric from the total underground-part area — it must
    # not be picked over the real "Площадь подземной части" / "Общая площадь
    # подземного паркинга" row that follows it.
    tz = DocxContent(
        paragraphs=[],
        tables=[[
            ["1", "Площадь застройки подземной части", "м2", "4 611"],
            ["2", "Общая площадь подземного паркинга", "м2", "13 297"],
        ]],
    )
    assert extractors.extract_underground_area(tz) == 13297.0


def test_extract_aboveground_area_ignores_footprint_row():
    tz = DocxContent(
        paragraphs=[],
        tables=[[
            ["1", "Площадь застройки наземной части", "м2", "3 587"],
            ["2", "Общая наземная площадь", "м2", "54 116"],
        ]],
    )
    assert extractors.extract_aboveground_area(tz) == 54116.0


def test_find_area_value_in_text_disambiguates_footprint_from_underground():
    lines = [
        "Площадь застройки подземной части м2 4 611",
        "Общая площадь подземного паркинга м2 13 297",
    ]
    value = extractors._find_area_value_in_text(
        lines, ('площад', 'подземн'),
        must_not_contain=('застройки',),
    )
    assert value == 13297.0


def test_find_area_value_in_text_ignores_trailing_alnum_token():
    # OCR text like "..., корпус 5А" must not have its trailing "5" picked
    # over the real value earlier on the same line.
    lines = ["Общая площадь м2 67 413, корпус 5А"]
    value = extractors._find_area_value_in_text(
        lines, ('обща', 'площад'),
        must_not_contain=('подземн', 'надземн', 'наземн'),
    )
    assert value == 67413.0


def test_find_area_value_in_text_same_line():
    lines = ["Общая площадь м2 67 413"]
    value = extractors._find_area_value_in_text(
        lines, ('обща', 'площад'),
        must_not_contain=('подземн', 'надземн', 'наземн'),
    )
    assert value == 67413.0


def test_find_area_value_in_text_next_line():
    lines = ["Площадь подземной части", "м2 13 297"]
    assert extractors._find_area_value_in_text(lines, ('площад', 'подземн')) == 13297.0


def test_find_area_value_in_text_disambiguates_total_from_subareas():
    lines = [
        "Общая площадь подземного паркинга м2 13 297",
        "Общая наземная площадь м2 54 116",
        "Общая площадь м2 67 413",
    ]
    value = extractors._find_area_value_in_text(
        lines, ('обща', 'площад'),
        must_not_contain=('подземн', 'надземн', 'наземн'),
    )
    assert value == 67413.0


def test_find_area_value_in_text_not_found():
    assert extractors._find_area_value_in_text(["Ничего релевантного"], ('обща', 'площад')) is None


def test_extract_total_area_rejects_split_caption_with_disqualifying_second_cell():
    # Regression: when a label is split across cells, must_not_contain must check
    # the entire label window, not just the narrow window that satisfied must_contain.
    # "Общая площадь" alone satisfies must_contain, but "надземной части" in the
    # adjacent cell should trigger must_not_contain disqualification.
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Общая площадь", "надземной части", "м2", "54 116"]]],
    )
    assert extractors.extract_total_area(tz) is None


def test_find_area_value_in_text_rejects_lookahead_with_disqualifying_word():
    # Regression: when looking ahead to the next line for a number, we must also
    # check the next line's content for must_not_contain words. Otherwise, a
    # disqualifying word on the lookahead line could slip past.
    lines = [
        "Общая площадь",
        "надземной части м2 54 116",
    ]
    value = extractors._find_area_value_in_text(
        lines, ('обща', 'площад'),
        must_not_contain=('подземн', 'надземн', 'наземн'),
    )
    assert value is None
