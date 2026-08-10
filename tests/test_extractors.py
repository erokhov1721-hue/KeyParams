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


# --- extract_building_class (synthetic) ---

def test_extract_building_class_found():
    dgp = DocxContent(paragraphs=["Жилой комплекс бизнес-класса."], tables=[])
    tz = DocxContent(paragraphs=[], tables=[])
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


def test_extract_area_label_split_across_two_cells():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["Площадь", "подземной части", "1 234"]]],
    )
    assert extractors.extract_underground_area(tz) == 1234.0


# --- real fixtures: documented expectations from the design spec ---

def test_real_general_contractor(real_dgp):
    assert extractors.extract_general_contractor(real_dgp) == "ООО «АНТТЕК»"


def test_real_signing_year_not_present(real_dgp):
    assert extractors.extract_signing_year(real_dgp) is None


def test_real_building_class_not_present(real_dgp, real_tz):
    assert extractors.extract_building_class(real_dgp, real_tz) is None


def test_real_underground_area_not_present(real_tz):
    assert extractors.extract_underground_area(real_tz) is None


def test_real_aboveground_area_not_present(real_tz):
    assert extractors.extract_aboveground_area(real_tz) is None


def test_real_total_area_not_present(real_tz):
    assert extractors.extract_total_area(real_tz) is None
