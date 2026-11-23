from app import comparison, history_check

OFF = comparison.Adjustments()


def _passport(name, building_class="Бизнес", area=1000.0, year=2024, **extra):
    return {
        "project_name": name, "building_class": building_class,
        "total_area_sqm": area, "year_signed": year, **extra,
    }


def _portfolio(rates, building_class="Бизнес", key="facade"):
    """Объекты одного класса площадью 1000 м², у каждого один вид работ —
    цена за м² равна переданной ставке."""
    passports = {f"p{i}": _passport(f"Объект {i}", building_class) for i in range(len(rates))}
    costs = {f"p{i}": {key: rate * 1000.0} for i, rate in enumerate(rates)}
    return passports, costs


def _by_name(rows):
    return {row["name"]: row for row in rows}


def test_an_object_far_above_its_class_is_flagged_red():
    passports, costs = _portfolio([100, 100, 100, 100, 150])

    rows = _by_name(history_check.build(passports, costs, OFF)["objects"])

    assert rows["Объект 4"]["level"] == "alert"
    assert rows["Объект 4"]["deviation_display"] == "+50,0 %"
    assert rows["Объект 0"]["level"] == "ok"


def test_a_noticeable_deviation_is_yellow_and_below_counts_too():
    passports, costs = _portfolio([100, 100, 100, 100, 80])

    rows = _by_name(history_check.build(passports, costs, OFF)["objects"])

    assert rows["Объект 4"]["level"] == "warn"


def test_the_reference_is_the_median_so_one_outlier_does_not_move_it():
    passports, costs = _portfolio([100, 100, 100, 100, 1000])

    report = history_check.build(passports, costs, OFF)

    assert report["classes"][0]["median"] == 100
    assert _by_name(report["objects"])["Объект 0"]["deviation"] == 0


def test_a_class_with_too_few_objects_is_shown_without_a_verdict():
    passports, costs = _portfolio([100, 100, 300])

    report = history_check.build(passports, costs, OFF)

    row = _by_name(report["objects"])["Объект 2"]
    assert row["level"] == "none"
    assert row["deviation_display"] == "+200,0 %"
    assert row["note"] == "мало объектов для сравнения"
    assert report["classes"][0]["confidence"] == "few"
    assert report["counts"]["objects"] == 0


def test_objects_are_only_compared_within_their_own_class():
    business, business_costs = _portfolio([100, 100, 100, 100])
    comfort = {f"c{i}": _passport(f"Комфорт {i}", "Комфорт") for i in range(4)}
    comfort_costs = {f"c{i}": {"facade": 50_000.0} for i in range(4)}

    report = history_check.build({**business, **comfort}, {**business_costs, **comfort_costs}, OFF)

    assert all(row["level"] == "ok" for row in report["objects"])


def test_inflation_brings_an_old_contract_to_todays_prices():
    passports, costs = _portfolio([100, 100, 100, 100])
    passports["p0"]["year_signed"] = 2020
    costs["p0"] = {"facade": 100_000.0 / 1.1 ** 4}
    adjustments = comparison.Adjustments(inflation=10.0, target_year=2024)

    rows = _by_name(history_check.build(passports, costs, adjustments)["objects"])

    assert round(rows["Объект 0"]["rate"]) == 100
    assert rows["Объект 0"]["level"] == "ok"


def test_an_object_without_a_year_stays_out_of_an_inflation_adjusted_comparison():
    passports, costs = _portfolio([100, 100, 100, 100, 500])
    passports["p4"]["year_signed"] = None
    adjustments = comparison.Adjustments(inflation=10.0, target_year=2024)

    report = history_check.build(passports, costs, adjustments)

    row = _by_name(report["objects"])["Объект 4"]
    assert row["rate"] is None
    assert row["level"] == "none"
    assert "год подписания неизвестен" in row["note"]
    assert any(
        issue["name"] == "Объект 4" and "год" in issue["problem"] for issue in report["data"]
    )


def test_a_small_object_above_its_class_carries_a_note_about_its_size():
    passports, costs = _portfolio([100, 100, 100, 100])
    passports["small"] = _passport("Малыш", area=100.0)
    costs["small"] = {"facade": 20_000.0}   # 200 ₽/м²

    row = _by_name(history_check.build(passports, costs, OFF)["objects"])["Малыш"]

    assert row["level"] == "alert"
    assert "маленький объект" in row["note"]


def test_works_report_lists_only_the_work_types_that_stand_out():
    passports = {f"p{i}": _passport(f"Объект {i}") for i in range(5)}
    costs = {f"p{i}": {"facade": 100_000.0, "roof": 10_000.0} for i in range(5)}
    costs["p4"]["roof"] = 20_000.0

    works = history_check.build(passports, costs, OFF)["works"]

    assert [(row["name"], row["work_key"]) for row in works] == [("Объект 4", "roof")]
    assert works[0]["level"] == "alert"
    assert works[0]["deviation_display"] == "+100,0 %"
    # (20 − 10) ₽/м² × 1000 м²
    assert works[0]["impact_display"] == "+10 000 ₽"


def test_a_work_type_too_few_objects_have_is_not_judged():
    passports = {f"p{i}": _passport(f"Объект {i}") for i in range(5)}
    costs = {f"p{i}": {"facade": 100_000.0} for i in range(5)}
    costs["p0"]["restoration"] = 5_000.0
    costs["p1"]["restoration"] = 500_000.0

    assert history_check.build(passports, costs, OFF)["works"] == []


def _summary_row(base, signed, predicted=None):
    return {"base": base, "signed": signed, "predicted": predicted, "has_increase_data": True}


def test_increase_is_compared_in_percentage_points_against_the_class():
    passports, costs = _portfolio([100, 100, 100, 100, 100])
    summary = {f"p{i}": _summary_row(100.0, 10.0) for i in range(4)}
    summary["p4"] = _summary_row(100.0, 20.0, 15.0)

    report = history_check.build(passports, costs, OFF, summary)

    row = _by_name(report["increase"])["Объект 4"]
    assert row["share_display"] == "35,0 %"
    assert row["deviation_display"] == "+25,0 п.п."
    assert row["level"] == "alert"
    assert report["counts"]["increase"] == 1


def test_an_object_without_increase_data_is_left_out_of_the_increase_report():
    passports, costs = _portfolio([100, 100, 100, 100, 100])
    summary = {f"p{i}": _summary_row(100.0, 10.0) for i in range(4)}
    summary["p4"] = {"base": 100.0, "signed": None, "predicted": None, "has_increase_data": False}

    names = _by_name(history_check.build(passports, costs, OFF, summary)["increase"])

    assert "Объект 4" not in names
    assert len(names) == 4


def test_data_report_names_missing_class_area_and_estimate():
    passports = {
        "a": _passport("Без класса", building_class=None),
        "b": _passport("Без площади", area=None),
        "c": _passport("Без сметы"),
    }
    costs = {"a": {"facade": 1.0}, "b": {"facade": 1.0}, "c": {}}

    problems = {
        (row["name"], row["problem"]) for row in history_check.build(passports, costs, OFF)["data"]
    }

    assert ("Без класса", "Не указан класс объекта") in problems
    assert ("Без площади", "Не указана общая площадь") in problems
    assert ("Без сметы", "Нет сметы") in problems


def test_data_report_flags_two_objects_sharing_one_area():
    passports = {
        "a": _passport("Первый", area=55947.07),
        "b": _passport("Второй", area=55947.07),
        "c": _passport("Третий", area=60000.0),
    }
    costs = {slug: {"facade": 1.0} for slug in passports}

    rows = history_check.build(passports, costs, OFF)["data"]

    flagged = {row["name"]: row["problem"] for row in rows}
    assert "Второй" in flagged["Первый"]
    assert "Первый" in flagged["Второй"]
    assert "Третий" not in flagged


def test_data_report_flags_an_estimate_with_far_fewer_work_types_than_usual():
    keys = ["facade", "roof", "concrete", "lifts", "utilities", "landscaping"]
    passports = {f"p{i}": _passport(f"Объект {i}", area=1000.0 + i) for i in range(4)}
    costs = {f"p{i}": {key: 1000.0 for key in keys} for i in range(4)}
    costs["p3"] = {"facade": 1000.0, "roof": 1000.0}

    rows = history_check.build(passports, costs, OFF)["data"]

    assert [(row["name"], row["level"]) for row in rows] == [("Объект 3", "warn")]
    assert "2 видов работ — обычно их 6" in rows[0]["problem"]


def test_choosing_a_class_narrows_every_report_but_not_the_class_list():
    business, business_costs = _portfolio([100, 100, 100, 100, 150])
    comfort = {f"c{i}": _passport(f"Комфорт {i}", "Комфорт", area=2000.0 + i) for i in range(4)}
    comfort_costs = {f"c{i}": {"facade": 50_000.0} for i in range(4)}

    report = history_check.build(
        {**business, **comfort}, {**business_costs, **comfort_costs}, OFF,
        building_class="Комфорт",
    )

    assert {row["building_class"] for row in report["objects"]} == {"Комфорт"}
    assert {row["building_class"] for row in report["classes"]} == {"Бизнес", "Комфорт"}
    assert report["counts"]["objects"] == 0
