from decimal import Decimal

from app import cost_increase, investor_summary, predicted_increase


def _report(rows, estimate=None):
    """A cost-increase report built from ready-made (name, было, стало)
    rows, the same way tests/test_comparison.py does it — through the real
    ``cost_increase.build_report`` rather than a hand-built fake, so this
    module's tests move if the increase calculation ever does.
    """
    lines = [cost_increase.Line(name, was, now) for name, was, now in rows]
    return cost_increase.build_report(lines, estimate)


def _predicted_report(rows):
    """A predicted-increase report from ready-made (name, amount) rows,
    through the real ``predicted_increase.build_report`` for the same
    reason ``_report`` above uses the real ``cost_increase.build_report``.
    """
    lines = [predicted_increase.Line(name, Decimal(str(amount))) for name, amount in rows]
    return predicted_increase.build_report(lines)


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


# --- разделы, которые дорожают по прогнозируемому удорожанию ---

def test_increasing_sections_lists_only_sections_that_got_dearer():
    # Прогноз уже сам по себе — сумма удорожания по разделу, а не пара
    # «было»/«стало»: отрицательная сумма (например, оптимизация по фасаду)
    # это единственный способ у раздела в предсказании не быть подорожавшим.
    predicted = _predicted_report([("Кровля", 30.0), ("Фасадные работы", -10.0)])
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0, "facade": 100.0}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
        predicted_increase_reports_by_slug={"a": predicted},
        area_by_slug={},
    )
    sections = table["rows"][0]["increasing_sections"]

    assert len(sections) == 1
    assert sections[0]["label"] == "Кровли"
    assert sections[0]["estimate_display"] == "100 ₽"
    assert sections[0]["current_display"] == "130 ₽"
    assert sections[0]["per_sqm_display"] == "—"
    assert sections[0]["percent_display"] == "+30,0 %"


def test_increasing_sections_come_biggest_delta_first():
    predicted = _predicted_report([("Кровля", 10.0), ("Фасадные работы", 200.0)])
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0, "facade": 100.0}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
        predicted_increase_reports_by_slug={"a": predicted},
        area_by_slug={},
    )
    labels = [s["label"] for s in table["rows"][0]["increasing_sections"]]

    assert labels == ["Фасад", "Кровли"]


def test_increasing_sections_show_cost_per_square_metre():
    predicted = _predicted_report([("Кровля", 30.0)])
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
        predicted_increase_reports_by_slug={"a": predicted},
        area_by_slug={"a": 2.0},
    )
    section = table["rows"][0]["increasing_sections"][0]

    # 100 + 30 = 130 ₽ за 2 м² -> 65 ₽/м²
    assert section["per_sqm_display"] == "65 ₽/м²"


def test_a_section_new_to_the_estimate_is_named_new_work_not_a_dash():
    predicted = _predicted_report(
        [("Кровля", 10.0), ("Благоустройство, дороги", 5_000_000.0)],
    )
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
        predicted_increase_reports_by_slug={"a": predicted},
        area_by_slug={},
    )
    sections = {s["label"]: s for s in table["rows"][0]["increasing_sections"]}

    assert sections["Благоустройство"]["percent_display"] == "новые работы"


def test_neither_file_means_no_increasing_sections():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
        predicted_increase_reports_by_slug={"a": None},
        area_by_slug={},
    )
    assert table["rows"][0]["increasing_sections"] == []
    assert table["rows"][0]["has_increase_data"] is False


def test_a_predicted_file_marks_the_object_as_having_data():
    predicted = _predicted_report([("Кровля", 30.0)])
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={},
        predicted_increase_reports_by_slug={"a": predicted},
        area_by_slug={},
    )
    assert table["rows"][0]["has_increase_data"] is True


def test_a_signed_file_without_a_predicted_one_still_lists_increasing_sections():
    # Объект вроде Veer: файл удорожания загружен, прогнозируемого — нет.
    # Карточка деталей должна показывать раздел, который подорожал по
    # подписанному файлу, а не молчать, будто данных вообще нет.
    report = _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        predicted_increase_by_slug={},
        predicted_increase_reports_by_slug={"a": None},
        area_by_slug={},
    )
    row = table["rows"][0]
    assert row["has_increase_data"] is True
    sections = row["increasing_sections"]
    assert len(sections) == 1
    assert sections[0]["label"] == "Кровли"
    assert sections[0]["current_display"] == "130 ₽"
    assert sections[0]["percent_display"] == "+30,0 %"


def test_a_signed_file_without_an_estimate_does_not_count_toward_increasing_sections():
    # Без сметы «стало» подписанного файла сравнивается само с собой
    # («было»/«стало»), а не со сметой — той же базой, что и у прогноза.
    # Смешивать эту дельту с прогнозной значило бы складывать разное как одно.
    report = _report([("Кровля", 100.0, 130.0)], estimate=None)
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": report},
        predicted_increase_by_slug={},
        predicted_increase_reports_by_slug={"a": None},
        area_by_slug={},
    )
    row = table["rows"][0]
    assert row["has_increase_data"] is False
    assert row["increasing_sections"] == []


def test_signed_and_predicted_increase_combine_on_the_same_section():
    report = _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})
    predicted = _predicted_report([("Кровля", 20.0)])
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        predicted_increase_by_slug={},
        predicted_increase_reports_by_slug={"a": predicted},
        area_by_slug={},
    )
    sections = table["rows"][0]["increasing_sections"]

    assert len(sections) == 1
    # 30 подписанных + 20 прогноза против сметы в 100 -> 150, +50 %.
    assert sections[0]["current_display"] == "150 ₽"
    assert sections[0]["percent_display"] == "+50,0 %"


# --- смета против итоговой стоимости ---

def test_estimate_vs_total_is_an_overrun_when_the_total_is_bigger():
    report = _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        predicted_increase_by_slug={"a": 50.0},
    )
    evt = table["rows"][0]["estimate_vs_total"]

    # смета 100, подписанное 30, прогноз 50 -> итог 180, перерасход 80 (+80%)
    assert evt["overrun_display"] == "+80 ₽"
    assert evt["percent_display"] == "+80,0 %"
    assert evt["is_overrun"] is True
    assert evt["is_savings"] is False


def test_estimate_vs_total_is_savings_when_the_total_is_smaller():
    report = _report([("Кровля", 100.0, 60.0)], {"roof": 100.0})
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        predicted_increase_by_slug={},
    )
    evt = table["rows"][0]["estimate_vs_total"]

    # смета 100, подписанное −40 -> итог 60, экономия 40 (−40%)
    assert evt["overrun_display"] == "−40 ₽"
    assert evt["percent_display"].startswith("−")
    assert evt["is_overrun"] is False
    assert evt["is_savings"] is True


def test_estimate_vs_total_is_none_without_an_estimate():
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {}},
        cost_increase_reports_by_slug={"a": None},
        predicted_increase_by_slug={"a": 50.0},
    )
    assert table["rows"][0]["estimate_vs_total"] is None


# --- итоговая стоимость объекта за м² ---

def test_total_per_sqm_is_the_total_cost_over_the_objects_area():
    report = _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        predicted_increase_by_slug={},
        area_by_slug={"a": 2.0},
    )
    # смета 100 + подписанное 30 = итог 130 ₽ за 2 м² -> 65 ₽/м²
    assert table["rows"][0]["total_per_sqm_display"] == "65 ₽/м²"


def test_total_per_sqm_is_a_dash_without_an_area():
    report = _report([("Кровля", 100.0, 130.0)], {"roof": 100.0})
    table = investor_summary.build_table(
        ["a"], {"a": "Объект А"},
        estimate_totals_by_slug={"a": {"roof": 100.0}},
        cost_increase_reports_by_slug={"a": report},
        predicted_increase_by_slug={},
    )
    assert table["rows"][0]["total_per_sqm_display"] == "—"
