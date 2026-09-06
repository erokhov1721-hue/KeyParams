from app import cost_increase, investor_summary


def _report(rows, estimate=None):
    """A cost-increase report built from ready-made (name, было, стало)
    rows, the same way tests/test_comparison.py does it — through the real
    ``cost_increase.build_report`` rather than a hand-built fake, so this
    module's tests move if the increase calculation ever does.
    """
    lines = [cost_increase.Line(name, was, now) for name, was, now in rows]
    return cost_increase.build_report(lines, estimate)


def test_estimate_is_the_sum_of_its_sections():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0, "facade": 300.0}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
    )
    assert table["rows"][0]["estimate"] == 400.0


def test_missing_estimate_is_a_dash_not_zero():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
    )
    row = table["rows"][0]
    assert row["estimate"] is None
    assert row["estimate_display"] == "—"


def test_predicted_overrun_comes_straight_from_the_predicted_increase_map():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={"a": 500.0},
    )
    assert table["rows"][0]["predicted"] == 500.0


def test_object_with_no_predicted_increase_file_gets_a_dash():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
    )
    assert table["rows"][0]["predicted"] is None


def test_signed_overrun_is_the_reports_total_delta_against_the_estimate():
    report = _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        predicted_increase_by_slug={},
    )
    assert table["rows"][0]["signed"] == 30.0


def test_no_cost_increase_file_is_a_dash():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
    )
    assert table["rows"][0]["signed"] is None


def test_report_not_measured_against_an_estimate_is_a_dash_not_a_misleading_delta():
    # No estimate_totals passed to _report -> from_estimate is False, the
    # report's own delta is against "было", not comparable to the other
    # objects' figures.
    report = _report([("Кровля", 100.0, 130.0)])
    assert report.from_estimate is False
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": report},
        predicted_increase_by_slug={},
    )
    assert table["rows"][0]["signed"] is None


def test_total_cost_is_estimate_plus_signed_plus_predicted():
    report = _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        predicted_increase_by_slug={"a": 50.0},
    )
    # смета 100 + подписанное 30 (130 против сметы 100) + прогноз 50
    assert table["rows"][0]["total_cost"] == 180.0


def test_total_cost_sums_whatever_is_known_and_ignores_the_rest():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={"a": 50.0},
    )
    # ни сметы, ни подписанного удорожания нет — итог не дыра, а просто
    # известная часть.
    assert table["rows"][0]["total_cost"] == 50.0


def test_total_cost_is_a_dash_when_nothing_at_all_is_known():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
    )
    assert table["rows"][0]["total_cost"] is None
    assert table["rows"][0]["total_cost_display"] == "—"


def test_rows_are_sorted_by_project_name():
    table = investor_summary.build_table(
        ["b", "a"], {"a": "Аист", "b": "Берёза"},
        estimate_totals_by_slug={"a": {}, "b": {}},
        cost_increase_reports_by_slug={"a": None, "b": None},
        predicted_increase_by_slug={},
    )
    assert [row["slug"] for row in table["rows"]] == ["a", "b"]


def test_total_row_sums_only_known_values_and_counts_them():
    table = investor_summary.build_table(
        ["a", "b"], {"a": "А", "b": "Б"},
        estimate_totals_by_slug={"a": {"roof": 100.0}, "b": {}},
        cost_increase_reports_by_slug={"a": None, "b": None},
        predicted_increase_by_slug={"a": 10.0, "b": 20.0},
    )
    total = table["total"]
    assert total["count"] == 2
    assert total["estimate_count"] == 1
    assert total["estimate_display"] == "100 ₽"
    assert total["predicted_count"] == 2
    assert total["predicted_display"] == "30 ₽"
    assert total["total_cost_count"] == 2
    assert total["total_cost_display"] == "130 ₽"


def test_total_row_is_a_dash_when_nothing_is_known_for_that_column():
    table = investor_summary.build_table(
        ["a"], {"a": "А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
    )
    total = table["total"]
    assert total["estimate_display"] == "—"
    assert total["estimate_count"] == 0


def test_empty_project_list_gives_an_empty_table():
    table = investor_summary.build_table(
        [], {}, estimate_totals_by_slug={}, cost_increase_reports_by_slug={},
        predicted_increase_by_slug={},
    )
    assert table["rows"] == []
    assert table["total"]["count"] == 0
