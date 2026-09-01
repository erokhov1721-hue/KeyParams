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
        vis_overrun_by_slug={},
    )
    assert table["rows"][0]["estimate"] == 400.0


def test_missing_estimate_is_a_dash_not_zero():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        vis_overrun_by_slug={},
    )
    row = table["rows"][0]
    assert row["estimate"] is None
    assert row["estimate_display"] == "—"


def test_predicted_overrun_comes_straight_from_the_vis_map():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        vis_overrun_by_slug={"a": 500.0},
    )
    assert table["rows"][0]["predicted"] == 500.0


def test_object_the_registry_never_matched_gets_a_dash():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        vis_overrun_by_slug={},
    )
    assert table["rows"][0]["predicted"] is None


def test_signed_overrun_is_the_reports_total_delta_against_the_estimate():
    report = _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        vis_overrun_by_slug={},
    )
    assert table["rows"][0]["signed"] == 30.0


def test_no_cost_increase_file_is_a_dash():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": None},
        vis_overrun_by_slug={},
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
        vis_overrun_by_slug={},
    )
    assert table["rows"][0]["signed"] is None


def test_delta_is_predicted_minus_signed():
    report = _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        vis_overrun_by_slug={"a": 50.0},
    )
    assert table["rows"][0]["delta"] == 20.0


def test_delta_is_a_dash_when_either_side_is_missing():
    table = investor_summary.build_table(
        ["a", "b"], {"a": "А", "b": "Б"},
        estimate_totals_by_slug={"a": {}, "b": {}},
        cost_increase_reports_by_slug={"a": None, "b": None},
        vis_overrun_by_slug={"a": 50.0},
    )
    rows_by_slug = {row["slug"]: row for row in table["rows"]}
    assert rows_by_slug["a"]["delta"] is None
    assert rows_by_slug["b"]["delta"] is None


def test_delta_is_not_clamped_when_signed_exceeds_predicted():
    report = _report([("Кровля", 100.0, 200.0)], {"roof": 100.0})
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        vis_overrun_by_slug={"a": 50.0},
    )
    assert table["rows"][0]["delta"] == -50.0
    assert table["rows"][0]["delta_display"].startswith("−")


def test_rows_are_sorted_by_project_name():
    table = investor_summary.build_table(
        ["b", "a"], {"a": "Аист", "b": "Берёза"},
        estimate_totals_by_slug={"a": {}, "b": {}},
        cost_increase_reports_by_slug={"a": None, "b": None},
        vis_overrun_by_slug={},
    )
    assert [row["slug"] for row in table["rows"]] == ["a", "b"]


def test_total_row_sums_only_known_values_and_counts_them():
    table = investor_summary.build_table(
        ["a", "b"], {"a": "А", "b": "Б"},
        estimate_totals_by_slug={"a": {"roof": 100.0}, "b": {}},
        cost_increase_reports_by_slug={"a": None, "b": None},
        vis_overrun_by_slug={"a": 10.0, "b": 20.0},
    )
    total = table["total"]
    assert total["count"] == 2
    assert total["estimate_count"] == 1
    assert total["estimate_display"] == "100 ₽"
    assert total["predicted_count"] == 2
    assert total["predicted_display"] == "30 ₽"


def test_total_row_is_a_dash_when_nothing_is_known_for_that_column():
    table = investor_summary.build_table(
        ["a"], {"a": "А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        vis_overrun_by_slug={},
    )
    total = table["total"]
    assert total["estimate_display"] == "—"
    assert total["estimate_count"] == 0


def test_empty_project_list_gives_an_empty_table():
    table = investor_summary.build_table(
        [], {}, estimate_totals_by_slug={}, cost_increase_reports_by_slug={},
        vis_overrun_by_slug={},
    )
    assert table["rows"] == []
    assert table["total"]["count"] == 0
