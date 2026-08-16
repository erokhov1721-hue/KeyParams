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
