from decimal import Decimal

import pytest

from app import comparison
from app.comparison import Adjustments

NONE = Adjustments()
VAT_22 = Adjustments(vat_rate=22.0)
INFLATION_10 = Adjustments(inflation=10.0, target_year=2026)


def _passport(name="П", **fields):
    data = {"project_name": name, "year_signed": "2025", "total_area_sqm": 1000.0}
    data.update(fields)
    return data


# --- условия договора ---

def test_the_terms_table_puts_the_contract_conditions_side_by_side():
    passports = {
        "a": _passport("Левый", smr_term="33 (тридцать три месяца)",
                       performance_bond_pct="3%"),
        "b": _passport("Правый", smr_term="38 мес", vat="20%"),
    }

    terms = comparison.build_terms_table(["a", "b"], passports)

    rows = {row["label"]: row["cells"] for row in terms["rows"]}
    assert rows["Срок СМР (мес.)"] == ["33 (тридцать три месяца)", "38 мес"]
    assert rows["Performance bond, %"] == ["3%", "—"]
    assert rows["НДС"] == ["—", "20%"]


def test_the_terms_table_keeps_every_condition_as_a_row():
    # Пять условий — постоянный список: прочерк напротив проекта говорит, что
    # у него этого условия нет, и это тоже ответ.
    passports = {"a": _passport("Левый", vat="20%")}

    terms = comparison.build_terms_table(["a"], passports)

    assert [row["field"] for row in terms["rows"]] == comparison.TERMS_FIELDS


def test_there_is_no_terms_table_when_no_protocol_was_read():
    # Пять строк прочерков занимали бы место и ничего не сообщали.
    passports = {"a": _passport("Левый"), "b": _passport("Правый")}

    assert comparison.build_terms_table(["a", "b"], passports) is None


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
        "vat_mode": "custom", "vat": "22",
        "inflation_on": "1", "inflation": "12", "year": "2030",
    })

    assert adjustments.vat_rate == 22.0
    assert adjustments.inflation == 12.0
    assert adjustments.target_year == 2030
    assert adjustments.applied is True


def test_no_vat_mode_in_the_address_means_own_rate():
    # Neither of the three radios reaching the address (a fresh visit, or
    # someone editing the query string by hand) reads the same as the
    # explicit "own rate" choice — never as "bring to a rate" with no rate
    # to bring it to.
    adjustments = comparison.adjustments_from_args({})

    assert adjustments.vat_mode == "own"
    assert adjustments.vat_rate is None


def test_the_net_of_vat_mode_needs_no_figure_of_its_own():
    # "без НДС" is a target of exactly 0% — the mode alone says so, with no
    # accompanying ``vat`` figure required the way "custom" needs one.
    adjustments = comparison.adjustments_from_args({"vat_mode": "net"})

    assert adjustments.vat_rate == 0.0
    assert adjustments.applied is True


def test_a_custom_vat_mode_with_an_unreadable_figure_falls_back_to_the_default():
    adjustments = comparison.adjustments_from_args({"vat_mode": "custom", "vat": "абв"})

    assert adjustments.vat_rate == comparison.DEFAULT_VAT_RATE


def test_an_out_of_range_vat_rate_falls_back_to_the_default():
    # ?vat=99999 parses fine as a number but isn't a tax rate — treated the
    # same as an unreadable figure, not carried through into the maths.
    adjustments = comparison.adjustments_from_args({"vat_mode": "custom", "vat": "99999"})

    assert adjustments.vat_rate == comparison.DEFAULT_VAT_RATE


def test_an_out_of_range_inflation_falls_back_to_the_default():
    # A huge inflation figure compounded over decades overflows a float
    # power — rejected before it ever reaches that maths.
    adjustments = comparison.adjustments_from_args({"inflation_on": "1", "inflation": "1e308"})

    assert adjustments.inflation == comparison.DEFAULT_INFLATION


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


def test_vat_mode_reads_back_which_of_the_three_scenarios_is_active():
    assert Adjustments().vat_mode == "own"
    assert Adjustments(vat_rate=0.0).vat_mode == "net"
    assert Adjustments(vat_rate=22.0).vat_mode == "custom"


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


def test_a_target_of_zero_strips_vat_to_the_net_amount():
    # The "без НДС" scenario: two projects signed under different VAT rates
    # (20% pre-2026, 22% from 2026 — see passport.VAT_RATE_CHANGE_YEAR) both
    # land on their own net-of-VAT figure once brought to a 0% target.
    net_of_vat = Adjustments(vat_rate=0.0)

    factor_20, notes_20 = comparison.project_factor("20%", "2020", net_of_vat)
    factor_22, notes_22 = comparison.project_factor("22%", "2026", net_of_vat)

    assert round(1200.0 * factor_20, 6) == 1000.0
    assert round(1220.0 * factor_22, 6) == 1000.0
    assert notes_20 == notes_22 == []


def test_an_unknown_vat_rate_is_left_alone_and_said_so():
    factor, notes = comparison.project_factor(None, "2025", VAT_22)

    assert factor == 1.0
    assert comparison.NOTE_NO_VAT in notes


def test_an_impossible_source_vat_rate_is_treated_as_unknown():
    # A -100% (or lower) rate stored on the object would zero or flip the
    # sign of the denominator below — treated as unusable instead of
    # crashing the whole page.
    factor, notes = comparison.project_factor("-100%", "2025", VAT_22)

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


def test_heat_fill_is_red_and_maxed_out_at_the_deviation_scale():
    # +50% is exactly DEVIATION_SCALE — same point the .dev-bar already
    # clips at, so the heat fill reaches its own ceiling there too.
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("А"), "b": _passport("Б")},
        {"a": {"facade": 1_000_000.0}, "b": {"facade": 1_500_000.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][1]["heat_bg"] == (
        "color-mix(in srgb, var(--red) 40.0%, transparent)"
    )


def test_heat_fill_uses_its_own_fixed_blue_for_a_cost_decrease():
    # Its own --heat-savings, not --accent: --accent means "the theme's own
    # accent colour" (teal, indigo, blue depending on which theme/ui-theme
    # is active) and isn't reliably blue — a heat cell needs the *same*
    # blue regardless of theme, meaning "cheaper than the base project"
    # specifically, not "good" in the app's general sense.
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("А"), "b": _passport("Б")},
        {"a": {"facade": 1_000_000.0}, "b": {"facade": 500_000.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][1]["heat_bg"] == (
        "color-mix(in srgb, var(--heat-savings) 40.0%, transparent)"
    )


def test_heat_fill_intensity_scales_with_the_size_of_the_deviation():
    # +10% is a fifth of the way to the 50% ceiling — the mix should land a
    # fifth of the way between the floor (8%) and the ceiling (40%).
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("А"), "b": _passport("Б")},
        {"a": {"facade": 1_000_000.0}, "b": {"facade": 1_100_000.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][1]["heat_bg"] == (
        "color-mix(in srgb, var(--red) 14.4%, transparent)"
    )


def test_heat_fill_does_not_grow_past_the_deviation_scale():
    # +200% is way past the ±50% scale (already clipped in the .dev-bar) —
    # the fill should cap at the same maximum as an exact +50%, not keep
    # getting more solid with every extra percentage point past that.
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("А"), "b": _passport("Б")},
        {"a": {"facade": 1_000_000.0}, "b": {"facade": 3_000_000.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][1]["heat_bg"] == (
        "color-mix(in srgb, var(--red) 40.0%, transparent)"
    )


def test_heat_fill_is_maximal_when_a_value_drops_to_zero():
    # A real value going to zero (not "no data") is a full −100% deviation —
    # already computed correctly by _add_deviations without any division by
    # the (zero) target, so the heat fill just reads it like any other
    # deviation: maxed out, on the "cheaper" side.
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("А"), "b": _passport("Б")},
        {"a": {"facade": 9_752.0}, "b": {"facade": 0.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][1]["deviation_display"] == "−100%"
    assert facade["cells"][1]["heat_bg"] == (
        "color-mix(in srgb, var(--heat-savings) 40.0%, transparent)"
    )


def test_heat_fill_is_absent_from_the_base_column():
    # The base column is the reference point, not part of the heat scale —
    # it stays plain text even in heatmap view.
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("А"), "b": _passport("Б")},
        {"a": {"facade": 1_000_000.0}, "b": {"facade": 1_500_000.0}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][0]["heat_bg"] is None


def test_heat_fill_is_absent_without_a_deviation():
    # A project missing this section entirely has no figure and nothing to
    # compare — no fill, same as no bar.
    table = comparison.build_section_table(
        ["a", "b"], {"a": _passport("А"), "b": _passport("Б")},
        {"a": {"facade": 1_000_000.0}, "b": {}}, NONE,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert facade["cells"][1]["heat_bg"] is None


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


def test_the_stored_vat_rate_wins_over_the_signing_year_rule():
    # 2025 alone would derive 20% by the year rule - but a protocol was
    # uploaded and reads 15%, and that's what the project page and PDF
    # already show. Using the rule here instead would silently show a
    # second, different rate on this one page for the same project.
    table = comparison.build_section_table(
        ["a"], {"a": _passport(year_signed="2025", vat="15%", total_area_sqm=1000.0)},
        {"a": {"facade": 1_150_000.0}}, VAT_22,
    )

    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert round(facade["cells"][0]["value"], 2) == round(1150.0 * 122 / 115, 2)
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

    # Деньги — полным числом, а не в миллионах: цену договора сверяют с
    # самим договором, и «1 000 млн ₽» прячет как раз те знаки, по которым
    # сверяют.
    price = _metric(cards, "Цена работ по договору")
    assert price["left"] == "1 000 000 000 ₽"
    assert price["right"] == "2 000 000 000 ₽"
    assert price["delta_display"] == "+100,0 %"
    assert price["diff_display"] == "+1 000 000 000 ₽"
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

    assert _metric(cards, "Итого СМР по смете")["right"] == "150 000 000 ₽"
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


def test_sections_total_display_sums_the_deltas_the_same_way_each_row_does():
    # facade +200 ₽/м², roof −10 ₽/м² -> +190 ₽/м², formatted the same way
    # (_signed) as every row's own display — the waterfall's "Итого" row
    # reads this field directly instead of re-deriving it in JS.
    cards = _pair(
        left_fields={"total_area_sqm": 1_000.0},
        right_fields={"total_area_sqm": 1_000.0},
        left_costs={"facade": 100_000.0, "roof": 50_000.0},
        right_costs={"facade": 300_000.0, "roof": 40_000.0},
    )

    assert cards["sections_total_display"] == "+190 ₽/м²"


def test_sections_total_display_is_empty_without_section_data():
    cards = _pair(
        left_fields={"total_area_sqm": 1_000.0}, right_fields={"total_area_sqm": 1_000.0},
    )

    assert cards["sections"] == []
    assert cards["sections_total_display"] == ""


def test_sections_are_compared_in_roubles_when_an_area_is_missing():
    cards = _pair(
        left_fields={"total_area_sqm": None},
        right_fields={"total_area_sqm": 1_000.0},
        left_costs={"facade": 100_000_000.0},
        right_costs={"facade": 300_000_000.0},
    )

    assert cards["sections"][0]["display"] == "+200 000 000 ₽"


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


# --- переключатель «с учётом удорожания» ---

def test_with_the_toggle_off_the_cost_increase_file_is_ignored():
    table = comparison.build_section_table(
        ["a"], {"a": _passport(total_area_sqm=None)}, {"a": {"roof": 100.0}}, NONE,
        reports={"a": _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})},
    )

    roof = next(row for row in table["rows"] if row["key"] == "roof")
    assert roof["cells"][0]["value"] == 100.0
    assert table["use_increase"] is False


def test_with_the_toggle_on_a_restated_section_uses_its_current_figure():
    # «Кровля» переписана файлом удорожания на 130; фасада файл не касается
    # вовсе, и его цифра остаётся сметной.
    table = comparison.build_section_table(
        ["a"], {"a": _passport(total_area_sqm=None)},
        {"a": {"roof": 100.0, "facade": 200.0}}, NONE,
        reports={"a": _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})},
        use_increase=True,
    )

    roof = next(row for row in table["rows"] if row["key"] == "roof")
    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert roof["cells"][0]["value"] == 130.0
    assert facade["cells"][0]["value"] == 200.0
    assert table["total"]["cells"][0]["value"] == 330.0
    assert table["use_increase"] is True


def test_a_project_without_a_cost_increase_file_gets_a_note_when_the_toggle_is_on():
    table = comparison.build_section_table(
        ["a"], {"a": _passport()}, {"a": {"roof": 100.0}}, NONE,
        reports={"a": None}, use_increase=True,
    )

    assert comparison.NOTE_NO_INCREASE in table["columns"][0]["notes"]


def test_no_note_when_a_missing_cost_increase_file_does_not_matter():
    # Переключатель выключен — молчание файла удорожания ни на что не влияет,
    # и пометка о нём только сбивала бы с толку.
    table = comparison.build_section_table(
        ["a"], {"a": _passport()}, {"a": {"roof": 100.0}}, NONE,
        reports={"a": None},
    )

    assert comparison.NOTE_NO_INCREASE not in table["columns"][0]["notes"]


# --- прогноз удорожания ВИС ---

def test_vis_overrun_by_slug_matches_exact_names_case_and_space_insensitive():
    passports = {"a": _passport("Nicole 1"), "b": _passport("Mira")}
    rows = [
        {"name": "  nicole 1 ", "sum": Decimal("900000")},
        {"name": "Veer", "sum": Decimal("100000")},
    ]

    result = comparison.vis_overrun_by_slug(["a", "b"], passports, rows)

    assert result == {"a": Decimal("900000")}


def test_vis_overrun_by_slug_matches_a_project_name_with_an_extra_word():
    # Реальный случай: проект в KeyParams назван «Тушино 1 Cityzen», а в
    # реестре ВИС тот же объект назван короче — «Тушино 1».
    passports = {"a": _passport("Тушино 1 Cityzen")}
    rows = [{"name": "Тушино 1", "sum": Decimal("500000")}]

    result = comparison.vis_overrun_by_slug(["a"], passports, rows)

    assert result == {"a": Decimal("500000")}


def test_vis_overrun_by_slug_does_not_match_on_a_single_shared_word():
    # «Тушино 1» и «Тушино 12» делят слово «тушино», но ни один набор слов
    # не содержится в другом целиком — разные объекты, деньги не должны
    # перепутаться.
    passports = {"a": _passport("Тушино 12")}
    rows = [{"name": "Тушино 1", "sum": Decimal("500000")}]

    result = comparison.vis_overrun_by_slug(["a"], passports, rows)

    assert result == {}


def test_with_the_vis_toggle_off_the_registry_is_ignored():
    table = comparison.build_section_table(
        ["a"], {"a": _passport(total_area_sqm=None)}, {"a": {"utilities": 100.0}}, NONE,
        vis_overrun_by_slug={"a": Decimal("900000")},
    )

    utilities = next(row for row in table["rows"] if row["key"] == "utilities")
    assert utilities["cells"][0]["value"] == 100.0
    assert table["use_vis_overrun"] is False


def test_with_the_vis_toggle_on_the_forecast_is_added_to_utilities():
    table = comparison.build_section_table(
        ["a"], {"a": _passport(total_area_sqm=None)},
        {"a": {"utilities": 100.0, "facade": 200.0}}, NONE,
        vis_overrun_by_slug={"a": Decimal("900000")}, use_vis_overrun=True,
    )

    utilities = next(row for row in table["rows"] if row["key"] == "utilities")
    facade = next(row for row in table["rows"] if row["key"] == "facade")
    assert utilities["cells"][0]["value"] == 900100.0
    assert facade["cells"][0]["value"] == 200.0
    assert table["use_vis_overrun"] is True


def test_vis_toggle_adds_on_top_of_the_cost_increase_figure():
    # Оба переключателя разом: «стало» из файла удорожания — 130, и поверх
    # него прибавляется прогноз ВИС, а не поверх сметных 100.
    table = comparison.build_section_table(
        ["a"], {"a": _passport(total_area_sqm=None)}, {"a": {"utilities": 100.0}}, NONE,
        reports={"a": _report([("ВИС", 100.0, 130.0)], {"utilities": 100.0})},
        use_increase=True,
        vis_overrun_by_slug={"a": Decimal("50")}, use_vis_overrun=True,
    )

    utilities = next(row for row in table["rows"] if row["key"] == "utilities")
    assert utilities["cells"][0]["value"] == 180.0


def test_a_project_without_a_vis_match_gets_a_note_when_the_toggle_is_on():
    table = comparison.build_section_table(
        ["a"], {"a": _passport()}, {"a": {"roof": 100.0}}, NONE,
        vis_overrun_by_slug={}, use_vis_overrun=True,
    )

    assert comparison.NOTE_NO_VIS_OVERRUN in table["columns"][0]["notes"]


def test_no_vis_note_when_the_toggle_is_off():
    table = comparison.build_section_table(
        ["a"], {"a": _passport()}, {"a": {"roof": 100.0}}, NONE,
        vis_overrun_by_slug={},
    )

    assert comparison.NOTE_NO_VIS_OVERRUN not in table["columns"][0]["notes"]


# --- удорожание по проектам ---

def _report(rows, estimate=None):
    """Отчёт по удорожанию из готовых строк ``(название, было, стало)``.

    Собирается настоящим ``cost_increase.build_report``, а не подделкой: если
    правило расчёта удорожания изменится, сводка по проектам должна поехать
    вместе с ним, а не остаться верной по отношению к выдуманным данным.
    """
    from app import cost_increase

    lines = [cost_increase.Line(name, was, now) for name, was, now in rows]
    return cost_increase.build_report(lines, estimate)


def test_no_project_with_a_cost_increase_file_means_no_block():
    summary = comparison.build_increase_summary(
        ["a", "b"], {"a": _passport(), "b": _passport()}, {"a": None, "b": None}, NONE,
    )

    assert summary is None


def test_each_project_gets_its_total_increase():
    summary = comparison.build_increase_summary(
        ["a", "b"],
        {"a": _passport("Левый"), "b": _passport("Правый")},
        {
            "a": _report([("Кровля", 100.0, 130.0)], {"roof": 100.0}),
            "b": _report([("Кровля", 100.0, 90.0)], {"roof": 100.0}),
        },
        NONE,
    )

    left, right = summary["projects"]
    assert left["name"] == "Левый"
    assert left["percent"] == pytest.approx(30.0)
    assert left["percent_display"] == "+30,0 %"
    assert left["money_display"] == "+30 ₽"
    assert left["dearer"] is True
    assert right["percent"] == pytest.approx(-10.0)
    assert right["dearer"] is False


def test_a_project_without_a_file_is_left_out_and_counted():
    summary = comparison.build_increase_summary(
        ["a", "b"],
        {"a": _passport("Есть"), "b": _passport("Нет")},
        {"a": _report([("Кровля", 100.0, 130.0)], {"roof": 100.0}), "b": None},
        NONE,
    )

    assert [p["name"] for p in summary["projects"]] == ["Есть"]
    assert summary["projects_with_data"] == 1
    assert summary["projects_total"] == 2


def test_the_average_percentage_is_the_mean_over_projects():
    summary = comparison.build_increase_summary(
        ["a", "b"],
        {"a": _passport(), "b": _passport()},
        {
            "a": _report([("Кровля", 100.0, 110.0)], {"roof": 100.0}),
            "b": _report([("Кровля", 100.0, 130.0)], {"roof": 100.0}),
        },
        NONE,
    )

    assert summary["average_percent"] == pytest.approx(20.0)
    assert summary["average_percent_display"] == "+20,0 %"


def test_the_percentage_by_sum_is_kept_apart_from_the_average():
    # Маленький проект, подорожавший вдвое, тянет средний процент вверх, а на
    # сумму почти не влияет. Одно число вместо двух здесь врёт.
    summary = comparison.build_increase_summary(
        ["a", "b"],
        {"a": _passport(), "b": _passport()},
        {
            "a": _report([("Кровля", 10.0, 20.0)], {"roof": 10.0}),
            "b": _report([("Кровля", 1000.0, 1000.0)], {"roof": 1000.0}),
        },
        NONE,
    )

    assert summary["average_percent"] == pytest.approx(50.0)
    assert round(summary["weighted_percent"], 4) == round(10 / 1010 * 100, 4)
    assert summary["total_delta"] == pytest.approx(10.0)


def test_works_count_how_often_each_kind_of_work_gets_dearer():
    summary = comparison.build_increase_summary(
        ["a", "b", "c"],
        {slug: _passport() for slug in ("a", "b", "c")},
        {
            "a": _report([("Фасадные работы", 100.0, 110.0), ("Кровля", 100.0, 110.0)],
                         {"facade": 100.0, "roof": 100.0}),
            "b": _report([("Фасадные работы", 100.0, 120.0), ("Кровля", 100.0, 100.0)],
                         {"facade": 100.0, "roof": 100.0}),
            "c": _report([("Фасадные работы", 100.0, 130.0)], {"facade": 100.0}),
        },
        NONE,
    )
    works = {row["key"]: row for row in summary["works"]}

    assert works["facade"]["frequency_display"] == "3 из 3"
    # Кровля есть только у двух проектов, и знаменатель — два, а не три:
    # раздела, которого у проекта нет, он не удорожал.
    assert works["roof"]["frequency_display"] == "1 из 2"


def test_works_come_biggest_increase_first():
    summary = comparison.build_increase_summary(
        ["a"],
        {"a": _passport()},
        {"a": _report(
            [("Кровля", 100.0, 110.0), ("Фасадные работы", 100.0, 200.0),
             ("Котлован", 100.0, 90.0)],
            {"roof": 100.0, "facade": 100.0, "excavation": 100.0},
        )},
        NONE,
    )

    assert [row["key"] for row in summary["works"]] == ["facade", "roof", "excavation"]
    assert summary["works"][-1]["dearer"] is False
    assert summary["works"][-1]["frequency_display"] == "0 из 1"


def test_the_widest_bar_belongs_to_the_biggest_increase():
    summary = comparison.build_increase_summary(
        ["a"],
        {"a": _passport()},
        {"a": _report(
            [("Фасадные работы", 100.0, 200.0), ("Кровля", 100.0, 125.0)],
            {"facade": 100.0, "roof": 100.0},
        )},
        NONE,
    )
    works = {row["key"]: row for row in summary["works"]}

    assert works["facade"]["width_pct"] == 100.0
    assert works["roof"]["width_pct"] == 25.0


def test_work_no_estimate_ever_priced_is_named_new_work_not_a_dash():
    summary = comparison.build_increase_summary(
        ["a"],
        {"a": _passport()},
        {"a": _report([("Благоустройство, дороги", 0.0, 5_000_000.0)], {"roof": 1.0})},
        NONE,
    )
    works = {row["key"]: row for row in summary["works"]}

    assert works["landscaping"]["avg_percent"] is None
    assert works["landscaping"]["avg_percent_display"] == "новые работы"


def test_the_corrections_move_the_money_and_leave_the_percentage_alone():
    # Поправка — постоянный множитель внутри проекта, и в отношении «стало» к
    # смете она сокращается. В рублях — нет, и общий итог по проектам разных
    # лет без неё складывать нельзя.
    passports = {"a": _passport(year_signed="2020")}
    reports = {"a": _report([("Кровля", 100.0, 200.0)], {"roof": 100.0})}

    plain = comparison.build_increase_summary(["a"], passports, reports, NONE)
    lifted = comparison.build_increase_summary(["a"], passports, reports, INFLATION_10)

    assert plain["projects"][0]["percent"] == pytest.approx(100.0)
    assert lifted["projects"][0]["percent"] == pytest.approx(100.0)
    assert lifted["total_delta"] > plain["total_delta"]


def test_a_project_without_an_estimate_is_named_so_its_baseline_is_not_taken_for_one():
    summary = comparison.build_increase_summary(
        ["a", "b"],
        {"a": _passport("Со сметой"), "b": _passport("Без сметы")},
        {
            "a": _report([("Кровля", 100.0, 130.0)], {"roof": 100.0}),
            "b": _report([("Кровля", 100.0, 130.0)]),
        },
        NONE,
    )

    assert summary["without_estimate"] == ["Без сметы"]


# --- удорожание на м² ---

def test_the_increase_per_square_metre_is_shown_for_every_project():
    summary = comparison.build_increase_summary(
        ["a", "b"],
        {"a": _passport("Левый", total_area_sqm=1000.0),
         "b": _passport("Правый", total_area_sqm=2000.0)},
        {
            "a": _report([("Кровля", 100_000.0, 200_000.0)], {"roof": 100_000.0}),
            "b": _report([("Кровля", 100_000.0, 150_000.0)], {"roof": 100_000.0}),
        },
        NONE,
    )

    assert summary["per_sqm"] is True
    left, right = summary["projects"]
    assert left["per_sqm"] == pytest.approx(100.0)
    assert left["per_sqm_display"] == "+100 ₽/м²"
    assert right["per_sqm"] == pytest.approx(25.0)
    # Итог — по всей площади выборки, а не среднее из двух ₽/м².
    assert summary["total_area"] == 3000.0
    assert summary["total_per_sqm"] == pytest.approx(150_000.0 / 3000.0)


def test_the_percentage_and_the_roubles_per_metre_are_scaled_apart():
    # Процент считается от собственной сметы проекта, и дешёвая смета даёт
    # большой процент на небольших деньгах. Порядок проектов по проценту и по
    # ₽/м² может быть обратным, поэтому и шкалы у полосок свои.
    summary = comparison.build_increase_summary(
        ["a", "b"],
        {"a": _passport("Мелкий", total_area_sqm=1000.0),
         "b": _passport("Крупный", total_area_sqm=1_000_000.0)},
        {
            # +100% на 100 тысячах — это 100 ₽/м².
            "a": _report([("Кровля", 100_000.0, 200_000.0)], {"roof": 100_000.0}),
            # +200% на миллионе — это всего 2 ₽/м².
            "b": _report([("Кровля", 1_000_000.0, 3_000_000.0)], {"roof": 1_000_000.0}),
        },
        NONE,
    )
    small, large = summary["projects"]

    assert large["width_pct"] == 100.0        # по проценту крупнее второй
    assert small["width_pct"] == 50.0
    assert small["per_sqm_width_pct"] == 100.0   # а по ₽/м² — первый
    assert large["per_sqm_width_pct"] == 2.0


def test_without_an_area_on_every_project_there_are_no_roubles_per_metre():
    # Смешивать в одном столбце рубли на метр и рубли просто нельзя, а итог по
    # части выборки выглядел бы как итог по всей.
    summary = comparison.build_increase_summary(
        ["a", "b"],
        {"a": _passport("С площадью", total_area_sqm=1000.0),
         "b": _passport("Без площади", total_area_sqm=None)},
        {
            "a": _report([("Кровля", 100_000.0, 200_000.0)], {"roof": 100_000.0}),
            "b": _report([("Кровля", 100_000.0, 150_000.0)], {"roof": 100_000.0}),
        },
        NONE,
    )

    assert summary["per_sqm"] is False
    assert summary["total_per_sqm"] is None
    assert summary["total_per_sqm_display"] == "—"
    assert summary["projects"][1]["per_sqm_display"] == "—"
    # И у видов работ тоже: сумма по двум проектам, поделённая на площадь
    # одного, — не рубли на метр, а просто большое число.
    assert all(row["per_sqm"] is None for row in summary["works"])


def test_a_kind_of_work_is_divided_by_the_area_of_the_projects_that_have_it():
    summary = comparison.build_increase_summary(
        ["a", "b"],
        {"a": _passport(total_area_sqm=1000.0), "b": _passport(total_area_sqm=1000.0)},
        {
            "a": _report(
                [("Кровля", 100_000.0, 200_000.0), ("Фасадные работы", 100_000.0, 150_000.0)],
                {"roof": 100_000.0, "facade": 100_000.0},
            ),
            "b": _report([("Кровля", 100_000.0, 200_000.0)], {"roof": 100_000.0}),
        },
        NONE,
    )
    works = {row["key"]: row for row in summary["works"]}

    # Кровля есть у обоих: 200 000 на 2000 м².
    assert works["roof"]["per_sqm"] == pytest.approx(100.0)
    # Фасад — только у первого, и делится на его 1000 м², а не на 2000:
    # размазывать удорожание одного проекта по метрам второго нечестно.
    assert works["facade"]["per_sqm"] == pytest.approx(50.0)


def test_the_corrections_move_the_roubles_per_metre_but_not_the_area():
    # Квадратный метр 2020 года это квадратный метр 2026-го: поправляется
    # только то, что в рублях.
    passports = {"a": _passport(year_signed="2020", total_area_sqm=1000.0)}
    reports = {"a": _report([("Кровля", 100_000.0, 200_000.0)], {"roof": 100_000.0})}

    plain = comparison.build_increase_summary(["a"], passports, reports, NONE)
    lifted = comparison.build_increase_summary(["a"], passports, reports, INFLATION_10)

    assert plain["total_area"] == lifted["total_area"] == 1000.0
    assert lifted["total_per_sqm"] > plain["total_per_sqm"]


# --- средние по объектам ---

def test_there_is_no_averages_table_without_any_projects():
    assert comparison.build_averages_table([], {}, {}, NONE) is None


def test_ungrouped_averages_are_one_row_over_the_whole_selection():
    passports = {
        "a": _passport("А", total_area_sqm=1000.0, contract_price_rub=1_000_000.0),
        "b": _passport("Б", total_area_sqm=2000.0, contract_price_rub=3_000_000.0),
    }
    costs = {"a": {"facade": 1_000_000.0}, "b": {"facade": 2_000_000.0}}

    table = comparison.build_averages_table(["a", "b"], passports, costs, NONE)

    assert len(table["rows"]) == 1
    row = table["rows"][0]
    assert row["label"] == "Все объекты"
    assert row["count"] == 2
    # a: 1_000_000 / 1000 = 1000 ₽/м²; b: 2_000_000 / 2000 = 1000 ₽/м² — среднее 1000.
    assert row["per_sqm_avg"] == pytest.approx(1000.0)
    # (1_000_000 + 3_000_000) / 2
    assert row["contract_avg"] == pytest.approx(2_000_000.0)
    assert row["contract_display"] == "2 000 000 ₽"


def test_the_averages_row_is_portfolio_weighted_not_a_simple_mean_of_rates():
    # a: 1 000 000 / 1000 = 1000 ₽/м²; b: 1 000 000 / 4000 = 250 ₽/м². A
    # simple mean of the two rates would be 625; portfolio-weighted sums
    # cost and area separately first: 2 000 000 / 5000 = 400.
    passports = {
        "a": _passport("А", total_area_sqm=1000.0),
        "b": _passport("Б", total_area_sqm=4000.0),
    }
    costs = {"a": {"facade": 1_000_000.0}, "b": {"facade": 1_000_000.0}}

    table = comparison.build_averages_table(["a", "b"], passports, costs, NONE)

    assert table["rows"][0]["per_sqm_avg"] == pytest.approx(400.0)


def test_a_project_without_an_estimate_or_area_is_left_out_of_that_average():
    # Нет сметы у "b" — из среднего за м² он выпадает, но цена по договору у
    # него есть и в свой средний идёт.
    passports = {
        "a": _passport("А", total_area_sqm=1000.0, contract_price_rub=1_000_000.0),
        "b": _passport("Б", total_area_sqm=None, contract_price_rub=3_000_000.0),
    }
    costs = {"a": {"facade": 500_000.0}, "b": {}}

    table = comparison.build_averages_table(["a", "b"], passports, costs, NONE)

    row = table["rows"][0]
    assert row["per_sqm_avg"] == pytest.approx(500.0)
    assert row["contract_avg"] == pytest.approx(2_000_000.0)


def test_without_any_usable_figure_the_average_is_a_dash():
    passports = {"a": _passport("А", total_area_sqm=None, contract_price_rub=None)}
    table = comparison.build_averages_table(["a"], passports, {"a": {}}, NONE)

    row = table["rows"][0]
    assert row["per_sqm_avg"] is None
    assert row["per_sqm_display"] == "—"
    assert row["contract_avg"] is None
    assert row["contract_display"] == "—"


def test_grouping_by_contractor_splits_the_table_into_one_row_per_value():
    passports = {
        "a": _passport("А", general_contractor="ООО «АНТТЕК»", contract_price_rub=1_000_000.0),
        "b": _passport("Б", general_contractor="ООО «АНТТЕК»", contract_price_rub=3_000_000.0),
        "c": _passport("В", general_contractor="ООО «ГЭС»", contract_price_rub=2_000_000.0),
    }

    table = comparison.build_averages_table(
        ["a", "b", "c"], passports, {}, NONE, group_by="contractor",
    )

    rows = {row["label"]: row for row in table["rows"]}
    assert rows["ООО «АНТТЕК»"]["count"] == 2
    assert rows["ООО «АНТТЕК»"]["contract_avg"] == pytest.approx(2_000_000.0)
    assert rows["ООО «ГЭС»"]["count"] == 1
    assert rows["ООО «ГЭС»"]["contract_avg"] == pytest.approx(2_000_000.0)


def test_a_project_without_the_grouped_field_gets_its_own_not_set_row():
    passports = {
        "a": _passport("А", general_contractor="ООО «АНТТЕК»"),
        "b": _passport("Б", general_contractor=None),
    }

    table = comparison.build_averages_table(
        ["a", "b"], passports, {}, NONE, group_by="contractor",
    )

    labels = [row["label"] for row in table["rows"]]
    assert "Не указано" in labels
    # "Не указано" всегда последним, как и в фильтре списка проектов.
    assert labels[-1] == "Не указано"


def test_grouping_by_year_reads_the_year_out_of_a_free_form_date():
    passports = {
        "a": _passport("А", year_signed="от 2024 г."),
        "b": _passport("Б", year_signed="2025"),
    }

    table = comparison.build_averages_table(
        ["a", "b"], passports, {}, NONE, group_by="year",
    )

    labels = [row["label"] for row in table["rows"]]
    # Года по убыванию, как в фильтре.
    assert labels == ["2025", "2024"]


def test_corrections_reach_the_averages():
    passports = {"a": _passport("А", year_signed="2020", contract_price_rub=1_000_000.0)}

    plain = comparison.build_averages_table(["a"], passports, {}, NONE)
    lifted = comparison.build_averages_table(["a"], passports, {}, INFLATION_10)

    assert lifted["rows"][0]["contract_avg"] > plain["rows"][0]["contract_avg"]


def test_the_work_breakdown_averages_per_square_metre_across_the_whole_selection():
    passports = {
        "a": _passport("А", total_area_sqm=1000.0),
        "b": _passport("Б", total_area_sqm=2000.0),
    }
    costs = {
        "a": {"facade": 1_000_000.0, "roof": 200_000.0},
        "b": {"facade": 4_000_000.0},
    }

    table = comparison.build_averages_table(["a", "b"], passports, costs, NONE)
    works = {row["key"]: row for row in table["works"]}

    # Портфельное: (1 000 000 + 4 000 000) / (1000 + 2000) = 1666,67 ₽/м² —
    # not the simple mean of a's 1000 and b's 2000.
    assert works["facade"]["avg_per_sqm"] == pytest.approx(5_000_000.0 / 3000.0)
    assert works["facade"]["frequency_display"] == "2 из 2"
    # Кровля есть только у "a", но знаменатель — оба объекта со сметой, а не
    # только тот, у которого раздел нашёлся: иначе «1 из 10» читалось бы как
    # «1 из 1», то есть как стопроцентное покрытие.
    assert works["roof"]["avg_per_sqm"] == pytest.approx(200.0)
    assert works["roof"]["frequency_display"] == "1 из 2"


def test_the_work_breakdown_denominator_counts_every_project_with_an_estimate():
    # Раздел есть только у одного объекта из трёх — знаменатель должен
    # показать все три, а не единицу.
    passports = {
        "a": _passport("А", total_area_sqm=1000.0),
        "b": _passport("Б", total_area_sqm=1000.0),
        "c": _passport("В", total_area_sqm=1000.0),
    }
    costs = {
        "a": {"facade": 1_000_000.0},
        "b": {"roof": 500_000.0},
        "c": {"roof": 500_000.0},
    }

    table = comparison.build_averages_table(["a", "b", "c"], passports, costs, NONE)
    works = {row["key"]: row for row in table["works"]}

    assert works["facade"]["frequency_display"] == "1 из 3"
    assert works["roof"]["frequency_display"] == "2 из 3"


def test_the_averages_row_shows_its_own_count_per_metric():
    # "a" has both figures, "b" only a price, "c" only an estimate+area.
    # Группа целиком — 3 объекта, но в каждом среднем участвует не все три.
    passports = {
        "a": _passport("А", total_area_sqm=1000.0, contract_price_rub=1_000_000.0),
        "b": _passport("Б", total_area_sqm=None, contract_price_rub=2_000_000.0),
        "c": _passport("В", total_area_sqm=1000.0, contract_price_rub=None),
    }
    costs = {"a": {"facade": 500_000.0}, "b": {}, "c": {"facade": 500_000.0}}

    table = comparison.build_averages_table(["a", "b", "c"], passports, costs, NONE)

    row = table["rows"][0]
    assert row["count"] == 3
    assert row["per_sqm_count"] == 2       # a, c
    assert row["contract_count"] == 2      # a, b


def test_a_project_whose_correction_cannot_apply_is_excluded_from_the_average():
    # "a" has a known signing year, "b" doesn't — with inflation switched on,
    # "b"'s figure would stay nominal while "a"'s gets lifted, and averaging
    # the two together would answer neither question honestly.
    passports = {
        "a": _passport("А", year_signed="2020", contract_price_rub=1_000_000.0),
        "b": _passport("Б", year_signed=None, contract_price_rub=1_000_000.0),
    }

    plain = comparison.build_averages_table(["a", "b"], passports, {}, NONE)
    lifted = comparison.build_averages_table(["a", "b"], passports, {}, INFLATION_10)

    assert plain["rows"][0]["contract_count"] == 2
    # Под инфляцией "b" исключается, а не тихо мешается с "a" в номинале.
    assert lifted["rows"][0]["contract_count"] == 1
    assert "Б" in lifted["excluded"]
    assert plain["excluded"] == []


# --- сравнение объекта со средним по классу ---

def test_class_average_comparison_is_none_without_a_building_class():
    passports = {"a": _passport("А", building_class=None)}

    assert comparison.build_class_average_comparison("a", passports, {}, NONE) is None


def test_class_average_comparison_is_none_without_a_peer_of_the_same_class():
    passports = {
        "a": _passport("А", building_class="Бизнес"),
        "b": _passport("Б", building_class="Комфорт"),
    }

    assert comparison.build_class_average_comparison("a", passports, {}, NONE) is None


def test_class_average_comparison_computes_the_per_sqm_deviation():
    passports = {
        "a": _passport("Проспект мира", building_class="Бизнес", total_area_sqm=1000.0),
        "b": _passport("Б", building_class="Бизнес", total_area_sqm=1000.0),
        "c": _passport("В", building_class="Бизнес", total_area_sqm=1000.0),
        # Другой класс — не должен попасть в среднее.
        "d": _passport("Г", building_class="Комфорт", total_area_sqm=1000.0),
    }
    costs = {
        "a": {"facade": 1_500_000.0},   # 1500 ₽/м²
        "b": {"facade": 1_000_000.0},   # 1000 ₽/м²
        "c": {"facade": 1_000_000.0},   # 1000 ₽/м²
        "d": {"facade": 10_000_000.0},  # заведомо другой класс
    }

    result = comparison.build_class_average_comparison("a", passports, costs, NONE)

    assert result["building_class"] == "Бизнес"
    assert result["peer_count"] == 2       # b, c — не d и не сам a
    # Среднее по перам (b, c): 2 000 000 / 2000 = 1000 ₽/м².
    assert result["per_sqm"]["peer_avg_display"] == "1 000 ₽/м²"
    assert result["per_sqm"]["own_display"] == "1 500 ₽/м²"
    # a на 50% дороже своих же перов: (1500 / 1000 - 1) * 100 = 50%.
    assert result["per_sqm"]["deviation_pct"] == pytest.approx(50.0)
    assert result["per_sqm"]["deviation_display"] == "+50,0 %"


def test_class_average_comparison_work_rows_pair_each_type_with_its_deviation():
    passports = {
        "a": _passport("А", building_class="Бизнес", total_area_sqm=1000.0),
        "b": _passport("Б", building_class="Бизнес", total_area_sqm=1000.0),
    }
    costs = {
        "a": {"facade": 1_200_000.0, "roof": 100_000.0},
        "b": {"facade": 1_000_000.0},
    }

    result = comparison.build_class_average_comparison("a", passports, costs, NONE)
    works = {row["key"]: row for row in result["works"]}

    assert works["facade"]["peer_avg"] == pytest.approx(1000.0)
    assert works["facade"]["own_value"] == pytest.approx(1200.0)
    assert works["facade"]["deviation_pct"] == pytest.approx(20.0)
    # "roof" не встречается ни у одного пера — нет базы для процента.
    assert works["roof"]["peer_avg"] is None
    assert works["roof"]["own_value"] == pytest.approx(100.0)
    assert works["roof"]["deviation_pct"] is None
    assert works["roof"]["deviation_display"] == "—"


def test_class_average_comparison_chart_scales_every_bar_to_one_shared_max():
    # a: (1 200 000 + 200 000) / 1000 = 1400 ₽/м² за м²; b (пер): 1 000 000
    # / 1000 = 1000 ₽/м². Самое большое число на всей странице — 1400 (свой
    # показатель «за м²»), и от него берётся высота каждого столбика.
    passports = {
        "a": _passport("А", building_class="Бизнес", total_area_sqm=1000.0),
        "b": _passport("Б", building_class="Бизнес", total_area_sqm=1000.0),
    }
    costs = {
        "a": {"facade": 1_200_000.0, "roof": 200_000.0},
        "b": {"facade": 1_000_000.0},
    }

    result = comparison.build_class_average_comparison("a", passports, costs, NONE)
    chart = {row["key"]: row for row in result["chart"]}

    assert [row["key"] for row in result["chart"]] == ["per_sqm", "facade", "roof"]
    assert chart["per_sqm"]["own_value"] == pytest.approx(1400.0)
    assert chart["per_sqm"]["own_pct"] == pytest.approx(100.0)
    assert chart["per_sqm"]["peer_pct"] == pytest.approx(round(1000.0 / 1400.0 * 100.0, 1))
    assert chart["facade"]["peer_pct"] == pytest.approx(round(1000.0 / 1400.0 * 100.0, 1))
    assert chart["facade"]["own_pct"] == pytest.approx(round(1200.0 / 1400.0 * 100.0, 1))
    # "roof" не встречается ни у одного пера — нулевой столбик, не пропуск.
    assert chart["roof"]["peer_value"] is None
    assert chart["roof"]["peer_pct"] == 0
    assert chart["roof"]["own_pct"] == pytest.approx(round(200.0 / 1400.0 * 100.0, 1))


def test_excluded_work_keys_drop_that_type_everywhere_on_the_page():
    passports = {
        "a": _passport("А", building_class="Бизнес", total_area_sqm=1000.0),
        "b": _passport("Б", building_class="Бизнес", total_area_sqm=1000.0),
    }
    costs = {
        "a": {"facade": 1_200_000.0, "roof": 100_000.0},
        "b": {"facade": 1_000_000.0, "roof": 50_000.0},
    }

    result = comparison.build_class_average_comparison(
        "a", passports, costs, NONE, {"roof"},
    )

    assert "roof" not in {row["key"] for row in result["works"]}
    assert "roof" not in {row["key"] for row in result["chart"]}
    assert "facade" in {row["key"] for row in result["works"]}
    # "Стоимость за м²" считается заново без "roof" у обеих сторон — как
    # будто этого раздела не было в смете вовсе: у "a" остаётся только
    # facade (1 200 000 / 1000), у пера "b" — тоже только facade (1 000 000
    # / 1000), а не сумма всей сметы, как до исключения.
    assert result["per_sqm"]["own_display"] == "1 200 ₽/м²"
    assert result["per_sqm"]["peer_avg_display"] == "1 000 ₽/м²"


def test_the_work_breakdown_is_not_affected_by_the_group_switch():
    passports = {
        "a": _passport("А", total_area_sqm=1000.0, general_contractor="X"),
        "b": _passport("Б", total_area_sqm=2000.0, general_contractor="Y"),
    }
    costs = {"a": {"facade": 1_000_000.0}, "b": {"facade": 4_000_000.0}}

    ungrouped = comparison.build_averages_table(["a", "b"], passports, costs, NONE)
    grouped = comparison.build_averages_table(
        ["a", "b"], passports, costs, NONE, group_by="contractor",
    )

    assert grouped["works"] == ungrouped["works"]


def test_the_work_breakdown_sorts_the_costliest_first():
    passports = {"a": _passport("А", total_area_sqm=1000.0)}
    costs = {"a": {"facade": 3_000_000.0, "roof": 1_000_000.0}}

    table = comparison.build_averages_table(["a"], passports, costs, NONE)

    assert [row["key"] for row in table["works"]] == ["facade", "roof"]
