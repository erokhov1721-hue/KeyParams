from app import comparison
from app.comparison import Adjustments

NONE = Adjustments()
VAT_22 = Adjustments(vat_rate=22.0)
INFLATION_10 = Adjustments(inflation=10.0, target_year=2026)


def _passport(name="П", **fields):
    data = {"project_name": name, "year_signed": "2025", "total_area_sqm": 1000.0}
    data.update(fields)
    return data


# --- разбор настроек ---

def test_percent_is_read_however_it_is_written():
    assert comparison.parse_percent("12") == 12.0
    assert comparison.parse_percent("12 %") == 12.0
    assert comparison.parse_percent("12,5") == 12.5
    assert comparison.parse_percent(12) == 12.0
    assert comparison.parse_percent("не число") is None
    assert comparison.parse_percent(None) is None


def test_year_is_read_from_a_number_or_a_phrase():
    assert comparison.parse_year(2025) == 2025
    assert comparison.parse_year("2025") == 2025
    assert comparison.parse_year("от 2024 г.") == 2024
    assert comparison.parse_year("нет") is None


def test_corrections_are_off_unless_switched_on():
    adjustments = comparison.adjustments_from_args({})

    assert adjustments.vat_rate is None
    assert adjustments.inflation is None
    assert adjustments.applied is False
    assert adjustments.target_year == comparison.DEFAULT_TARGET_YEAR


def test_a_figure_alone_does_not_switch_a_correction_on():
    # The field keeps its value while the checkbox is clear, and an unticked
    # checkbox submits nothing — so the figure must not be the switch.
    adjustments = comparison.adjustments_from_args({"vat": "22", "inflation": "12"})

    assert adjustments.vat_rate is None
    assert adjustments.inflation is None


def test_switches_turn_the_corrections_on():
    adjustments = comparison.adjustments_from_args({
        "vat_on": "1", "vat": "22",
        "inflation_on": "1", "inflation": "12", "year": "2030",
    })

    assert adjustments.vat_rate == 22.0
    assert adjustments.inflation == 12.0
    assert adjustments.target_year == 2030
    assert adjustments.applied is True


def test_a_switch_with_an_unreadable_figure_falls_back_to_the_default():
    adjustments = comparison.adjustments_from_args({"vat_on": "1", "vat": "абв"})

    assert adjustments.vat_rate == comparison.DEFAULT_VAT_RATE


def test_zero_per_cent_is_a_correction_not_an_absence():
    # Zero still means "bring these to one year", and still marks the projects
    # whose year is unknown.
    adjustments = comparison.adjustments_from_args({"inflation_on": "1", "inflation": "0"})

    assert adjustments.inflation == 0.0
    assert adjustments.applied is True


def test_the_fields_show_the_defaults_while_switched_off():
    adjustments = comparison.adjustments_from_args({})

    assert adjustments.vat_display == "22"
    assert adjustments.inflation_display == "12"


# --- множитель проекта ---

def test_without_corrections_nothing_is_multiplied():
    factor, notes = comparison.project_factor("20%", "2020", NONE)

    assert factor == 1.0
    assert notes == []


def test_vat_is_brought_to_the_target_rate():
    factor, notes = comparison.project_factor("20%", "2025", VAT_22)

    assert round(factor, 6) == round(122 / 120, 6)
    assert notes == []


def test_the_same_vat_rate_changes_nothing():
    factor, _notes = comparison.project_factor("22%", "2026", VAT_22)

    assert factor == 1.0


def test_an_unknown_vat_rate_is_left_alone_and_said_so():
    factor, notes = comparison.project_factor(None, "2025", VAT_22)

    assert factor == 1.0
    assert comparison.NOTE_NO_VAT in notes


def test_inflation_carries_an_older_contract_forward():
    factor, notes = comparison.project_factor("20%", "2024", INFLATION_10)

    assert round(factor, 6) == round(1.1 ** 2, 6)
    assert notes == []


def test_inflation_carries_a_later_contract_back():
    factor, _notes = comparison.project_factor("20%", "2028", INFLATION_10)

    assert round(factor, 6) == round(1.1 ** -2, 6)


def test_zero_inflation_changes_nothing_but_is_still_applied():
    factor, notes = comparison.project_factor("20%", "2020", Adjustments(inflation=0.0))

    assert factor == 1.0
    assert notes == []


def test_an_unknown_year_is_left_alone_and_said_so():
    factor, notes = comparison.project_factor("20%", None, INFLATION_10)

    assert factor == 1.0
    assert comparison.NOTE_NO_YEAR in notes


def test_both_corrections_multiply_together():
    both = Adjustments(vat_rate=22.0, inflation=10.0, target_year=2026)

    factor, _notes = comparison.project_factor("20%", "2025", both)

    assert round(factor, 6) == round(122 / 120 * 1.1, 6)


# --- таблица ---

def test_without_a_single_estimate_there_is_no_table():
    table = comparison.build_section_table(
        ["a"], {"a": _passport()}, {"a": {}}, NONE,
    )

    assert table is None


def test_sections_are_shown_per_square_metre():
    table = comparison.build_section_table(
        ["a"], {"a": _passport(total_area_sqm=1000.0)},
        {"a": {"facade": 3_000_000.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][0]["value"] == 3000.0
    assert table["columns"][0]["per_sqm"] is True


def test_without_an_area_the_figures_stay_in_roubles():
    table = comparison.build_section_table(
        ["a"], {"a": _passport(total_area_sqm=None)},
        {"a": {"facade": 3_000_000.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][0]["value"] == 3_000_000.0
    assert table["columns"][0]["per_sqm"] is False
    assert comparison.NOTE_NO_AREA in table["columns"][0]["notes"]


def test_a_project_without_an_estimate_gets_dashes_and_a_note():
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("А"), "b": _passport("Б")},
        {"a": {"facade": 1_000_000.0}, "b": {}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][1]["value"] is None
    assert facade["cells"][1]["display"] == "—"
    assert comparison.NOTE_NO_ESTIMATE in table["columns"][1]["notes"]


def test_a_section_nobody_has_is_left_out_entirely():
    table = comparison.build_section_table(
        ["a"], {"a": _passport()}, {"a": {"facade": 1_000_000.0}}, NONE,
    )

    assert [row["key"] for row in table["rows"]] == ["facade"]


def test_a_section_that_cost_nothing_is_shown_as_nought():
    # Nought and "the estimate has no such section" are different facts.
    table = comparison.build_section_table(
        ["a"], {"a": _passport()},
        {"a": {"facade": 1_000_000.0, "landscaping": 0.0}}, NONE,
    )

    landscaping = next(row for row in table["rows"] if row["key"] == "landscaping")
    assert landscaping["cells"][0]["value"] == 0.0
    assert landscaping["cells"][0]["display"] == "0"


def test_deviation_is_measured_against_the_first_project():
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("А"), "b": _passport("Б")},
        {"a": {"facade": 1_000_000.0}, "b": {"facade": 1_500_000.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][0]["deviation"] is None
    assert round(facade["cells"][1]["deviation"], 3) == 0.5
    assert facade["cells"][1]["deviation_display"] == "+50%"


def test_the_total_line_adds_the_sections_up():
    table = comparison.build_section_table(
        ["a"], {"a": _passport(total_area_sqm=1000.0)},
        {"a": {"facade": 1_000_000.0, "roof": 500_000.0}}, NONE,
    )

    assert table["total"]["cells"][0]["value"] == 1500.0


def test_the_weight_bar_is_scaled_across_the_whole_table():
    # A facade is a third of the money and process equipment a fraction of a
    # per cent; a per-row bar would make every line look the same size.
    table = comparison.build_section_table(
        ["a"], {"a": _passport()},
        {"a": {"facade": 1_000_000.0, "technology": 10_000.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    technology = next(row for row in table["rows"] if row["key"] == "technology")
    assert facade["width_pct"] == 100.0
    assert technology["width_pct"] == 1.0


def test_corrections_reach_the_figures():
    table = comparison.build_section_table(
        ["a"], {"a": _passport(year_signed="2024", total_area_sqm=1000.0)},
        {"a": {"facade": 1_000_000.0}}, INFLATION_10,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert round(facade["cells"][0]["value"], 2) == round(1000.0 * 1.1 ** 2, 2)


def test_the_vat_rate_comes_from_the_signing_year_when_the_passport_has_none():
    # The passport's own vat field is only filled once a contract-terms
    # protocol has been uploaded; the rule by year works for every project.
    table = comparison.build_section_table(
        ["a"], {"a": _passport(year_signed="2025", vat=None, total_area_sqm=1000.0)},
        {"a": {"facade": 1_200_000.0}}, VAT_22,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert round(facade["cells"][0]["value"], 2) == round(1200.0 * 122 / 120, 2)
    assert table["columns"][0]["notes"] == []


# --- карточки двух объектов ---

def _pair(left_fields=None, right_fields=None, left_costs=None, right_costs=None,
          adjustments=NONE):
    passports = {
        "a": _passport("Левый", **(left_fields or {})),
        "b": _passport("Правый", **(right_fields or {})),
    }
    costs = {"a": left_costs or {}, "b": right_costs or {}}
    return comparison.build_pair_cards("a", "b", passports, costs, adjustments)


def _metric(cards, label):
    return next(m for m in cards["metrics"] if m["label"].startswith(label))


def test_the_cards_put_the_two_objects_side_by_side():
    cards = _pair(
        left_fields={"contract_price_rub": 1_000_000_000.0, "total_area_sqm": 10_000.0},
        right_fields={"contract_price_rub": 2_000_000_000.0, "total_area_sqm": 10_000.0},
    )

    price = _metric(cards, "Цена работ по договору")
    assert price["left"] == "1 000 млн ₽"
    assert price["right"] == "2 000 млн ₽"
    assert price["delta_display"] == "+100,0 %"
    assert price["diff_display"] == "+1 000 млн ₽"
    assert price["dearer"] is True


def test_a_cheaper_object_on_the_right_reads_as_better():
    cards = _pair(
        left_fields={"contract_price_rub": 2_000_000_000.0},
        right_fields={"contract_price_rub": 1_000_000_000.0},
    )

    assert _metric(cards, "Цена работ по договору")["dearer"] is False


def test_area_is_compared_without_being_called_better_or_worse():
    # A bigger building is neither.
    cards = _pair(
        left_fields={"total_area_sqm": 10_000.0},
        right_fields={"total_area_sqm": 20_000.0},
    )

    area = _metric(cards, "Общая площадь")
    assert area["left"] == "10 000 м²"
    assert area["delta_display"] == "+100,0 %"
    assert area["dearer"] is None


def test_the_estimate_total_is_a_card_of_its_own():
    cards = _pair(
        left_fields={"total_area_sqm": 1_000.0},
        right_fields={"total_area_sqm": 1_000.0},
        left_costs={"facade": 100_000_000.0},
        right_costs={"facade": 150_000_000.0},
    )

    assert _metric(cards, "Итого СМР по смете")["right"] == "150 млн ₽"
    assert _metric(cards, "Итого СМР на 1 м²")["right"] == "150 000 ₽/м²"


def test_a_figure_neither_object_has_is_shown_as_a_dash():
    cards = _pair()

    price = _metric(cards, "Цена работ по договору")
    assert price["left"] == "—"
    assert price["delta_display"] == ""
    assert price["diff_display"] == ""


def test_corrections_reach_the_cards_but_not_the_areas():
    cards = _pair(
        left_fields={"contract_price_rub": 1_000_000_000.0, "total_area_sqm": 10_000.0,
                     "year_signed": "2024"},
        right_fields={"contract_price_rub": 1_000_000_000.0, "total_area_sqm": 10_000.0,
                      "year_signed": "2026"},
        adjustments=INFLATION_10,
    )

    # The left-hand contract is two years older, so carrying both to 2026
    # makes it the dearer of the two.
    assert _metric(cards, "Цена работ по договору")["dearer"] is False
    # The areas are equal and stay equal: a square metre of 2024 is a square
    # metre of 2026, whatever the money did in between.
    assert _metric(cards, "Общая площадь")["delta_display"] == "+0,0 %"


def test_the_section_deltas_are_sorted_by_size():
    cards = _pair(
        left_fields={"total_area_sqm": 1_000.0},
        right_fields={"total_area_sqm": 1_000.0},
        left_costs={"facade": 100_000.0, "roof": 50_000.0},
        right_costs={"facade": 300_000.0, "roof": 40_000.0},
    )

    keys = [row["key"] for row in cards["sections"]]
    assert keys[0] == "facade"
    facade = cards["sections"][0]
    assert facade["dearer"] is True
    assert facade["display"] == "+200 ₽/м²"
    assert facade["width_pct"] == 100.0
    roof = next(row for row in cards["sections"] if row["key"] == "roof")
    assert roof["dearer"] is False
    assert roof["width_pct"] == 5.0


def test_sections_are_compared_in_roubles_when_an_area_is_missing():
    cards = _pair(
        left_fields={"total_area_sqm": None},
        right_fields={"total_area_sqm": 1_000.0},
        left_costs={"facade": 100_000_000.0},
        right_costs={"facade": 300_000_000.0},
    )

    assert cards["sections"][0]["display"] == "+200 млн ₽"


def test_there_are_no_cards_without_two_different_objects():
    passports = {"a": _passport("Один")}

    assert comparison.build_pair_cards("a", "a", passports, {}, NONE) is None
    assert comparison.build_pair_cards("a", None, passports, {}, NONE) is None
    assert comparison.build_pair_cards("a", "нет-такого", passports, {}, NONE) is None


# --- полоска доли раздела ---

def test_the_share_bar_is_scaled_against_the_base_column_alone():
    # Раньше ширина бралась по всем колонкам сразу: раздел, дорогой у
    # соседнего проекта, рисовался длинной полоской, хотя у базы там стояла
    # мелочь.
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("База"), "b": _passport("Сосед")},
        {"a": {"facade": 1_000_000.0, "waterproofing": 10_000.0},
         "b": {"facade": 1_000_000.0, "waterproofing": 900_000.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    waterproofing = next(row for row in table["rows"] if row["key"] == "waterproofing")
    assert facade["width_pct"] == 100.0
    assert waterproofing["width_pct"] == 1.0


def test_a_section_the_base_project_lacks_has_no_bar():
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("База"), "b": _passport("Сосед")},
        {"a": {"facade": 100.0}, "b": {"facade": 100.0, "lifts": 500.0}}, NONE,
    )

    lifts = next(row for row in table["rows"] if row["key"] == "lifts")
    assert lifts["width_pct"] == 0
    assert lifts["share_display"] == ""


def test_the_share_of_the_total_is_shown_beside_the_bar():
    table = comparison.build_section_table(
        ["a"], {"a": _passport()},
        {"a": {"facade": 280.0, "roof": 720.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert round(facade["share"], 1) == 28.0
    assert facade["share_display"] == "28%"


def test_a_share_under_ten_per_cent_keeps_one_decimal():
    # Разница между 0,4% и 1,6% существеннее, чем между 28% и 28,4%.
    table = comparison.build_section_table(
        ["a"], {"a": _passport()},
        {"a": {"facade": 984.0, "roof": 16.0}}, NONE,
    )

    roof = next(row for row in table["rows"] if row["key"] == "roof")
    assert roof["share_display"] == "1,6%"
