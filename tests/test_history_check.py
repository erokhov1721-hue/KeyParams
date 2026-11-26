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


# --- прогноз стоимости нового объекта ---

def _forecast_base(count=6, **costs_per_object):
    """``count`` объектов «Бизнеса» по 1000 м² с одинаковой сметой."""
    costs_per_object = costs_per_object or {"facade": 100_000.0, "roof": 20_000.0}
    passports = {f"p{i}": _passport(f"Объект {i}") for i in range(count)}
    costs = {f"p{i}": dict(costs_per_object) for i in range(count)}
    return passports, costs


def test_forecast_multiplies_the_typical_rate_of_each_work_type_by_the_new_area():
    passports, costs = _forecast_base()

    forecast = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 2000.0)

    assert forecast["problem"] is None
    amounts = {row["key"]: row["amount"] for row in forecast["works"]}
    assert amounts == {"facade": 200_000.0, "roof": 40_000.0}   # 100 и 20 ₽/м² × 2000 м²
    assert forecast["total"] == 240_000.0
    assert forecast["total_display"] == "240 000 ₽"
    assert forecast["rate_display"] == "120 ₽/м²"


def test_forecast_work_types_add_up_to_the_total():
    passports, costs = _forecast_base()
    costs["p0"] = {"facade": 150_000.0, "roof": 10_000.0, "lifts": 7_000.0}
    costs["p1"] = {"facade": 90_000.0, "roof": 35_000.0, "restoration": 50_000.0}

    forecast = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 3000.0)

    common = sum(row["amount"] for row in forecast["works"] if row["common"])
    rare = sum(
        row["amount"] * 1 / 6 for row in forecast["works"] if not row["common"]
    )
    assert round(common + rare, 6) == round(forecast["total"], 6)


def test_a_rare_work_type_enters_the_total_in_proportion_to_how_often_it_occurs():
    passports, costs = _forecast_base()
    costs["p0"]["restoration"] = 60_000.0   # 60 ₽/м², у одного из шести

    forecast = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 1000.0)

    rare = [row for row in forecast["works"] if not row["common"]]
    assert [row["key"] for row in rare] == ["restoration"]
    assert rare[0]["frequency_display"] == "1 из 6"
    # 120 ₽/м² обычных работ + 60 × 1/6 резерва
    assert round(forecast["rate"], 6) == 130.0
    assert forecast["reserve_display"] == "10 000 ₽"


def test_forecast_is_not_moved_by_one_object_with_a_wild_price():
    passports, costs = _forecast_base()
    costs["p0"] = {"facade": 5_000_000.0, "roof": 20_000.0}

    forecast = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 1000.0)

    assert round(forecast["rate"]) == 120


def test_forecast_leans_on_the_objects_closest_in_area():
    passports = {}
    costs = {}
    for i in range(4):   # маленькие и дорогие
        passports[f"s{i}"] = _passport(f"Малый {i}", area=5_000.0)
        costs[f"s{i}"] = {"facade": 5_000.0 * 300}
    for i in range(4):   # большие и дешёвые
        passports[f"b{i}"] = _passport(f"Большой {i}", area=200_000.0)
        costs[f"b{i}"] = {"facade": 200_000.0 * 100}

    small = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 5_000.0)
    large = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 200_000.0)

    assert small["rate"] > 250
    assert large["rate"] < 150
    assert small["analogs"][0]["name"].startswith("Малый")
    assert large["analogs"][0]["name"].startswith("Большой")


def test_forecast_uses_only_the_chosen_class():
    passports, costs = _forecast_base()
    for i in range(6):
        passports[f"c{i}"] = _passport(f"Комфорт {i}", "Комфорт")
        costs[f"c{i}"] = {"facade": 8_000.0, "roof": 2_000.0}

    forecast = history_check.build_forecast(passports, costs, OFF, None, "Комфорт", 1000.0)

    assert forecast["total"] == 10_000.0
    assert forecast["training_count"] == 6


def test_forecast_is_refused_for_a_class_with_too_few_objects():
    passports, costs = _forecast_base(count=3)

    forecast = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 1000.0)

    assert forecast["problem"] == "few"
    assert forecast["training_count"] == 3
    assert "works" not in forecast


def test_forecast_asks_for_a_class_and_an_area():
    passports, costs = _forecast_base()

    assert history_check.build_forecast(passports, costs, OFF, None, None, 1000.0)["problem"] == "no_class"
    assert history_check.build_forecast(passports, costs, OFF, None, "Бизнес", None)["problem"] == "no_area"
    assert history_check.build_forecast(passports, costs, OFF, None, "Бизнес", -5.0)["problem"] == "no_area"


def test_an_incomplete_estimate_is_kept_out_of_the_forecast_and_named():
    keys = ["facade", "roof", "concrete", "lifts", "utilities", "landscaping"]
    passports = {f"p{i}": _passport(f"Объект {i}") for i in range(6)}
    costs = {f"p{i}": {key: 10_000.0 for key in keys} for i in range(6)}
    costs["p5"] = {"facade": 10_000.0}

    forecast = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 1000.0)

    assert forecast["training_count"] == 5
    assert [row["name"] for row in forecast["skipped"]] == ["Объект 5"]
    assert "1 видов работ — обычно их 6" in forecast["skipped"][0]["reason"]
    assert forecast["total"] == 60_000.0


def test_forecast_reports_how_far_it_missed_on_past_objects():
    passports, costs = _forecast_base()
    costs["p0"] = {"facade": 150_000.0, "roof": 30_000.0}   # 180 ₽/м² против 120

    forecast = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 1000.0)

    assert forecast["backtest_count"] == 6
    worst = forecast["backtest"][0]
    assert worst["name"] == "Объект 0"
    assert worst["predicted_display"] == "120 ₽/м²"
    assert worst["actual_display"] == "180 ₽/м²"
    assert worst["error_display"] == "−33,3 %"
    assert forecast["typical_error_display"] == "0,0 %"
    assert forecast["worst_error_display"] == "33,3 %"
    # Диапазон «все прошлые объекты»: от 120 до 180 ₽/м² на 1000 м².
    assert forecast["extreme_display"] == "120 000 ₽ – 180 000 ₽"


def test_forecast_adds_the_typical_increase_of_the_class():
    passports, costs = _forecast_base()
    summary = {f"p{i}": _summary_row(100.0, 20.0) for i in range(6)}

    forecast = history_check.build_forecast(passports, costs, OFF, summary, "Бизнес", 1000.0)

    assert forecast["increase_share_display"] == "20,0 %"
    assert forecast["increase_display"] == "24 000 ₽"
    assert forecast["final_display"] == "144 000 ₽"
    assert forecast["final_per_sqm_display"] == "144 ₽/м²"


def test_forecast_without_increase_data_gives_the_estimate_alone():
    passports, costs = _forecast_base()

    forecast = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 1000.0)

    assert forecast["final"] is None
    assert forecast["increase_share_display"] is None
    assert forecast["total_display"] == "120 000 ₽"


def test_forecast_prices_are_brought_to_the_target_year():
    passports, costs = _forecast_base()
    for passport in passports.values():
        passport["year_signed"] = 2022
    adjustments = comparison.Adjustments(inflation=10.0, target_year=2024)

    forecast = history_check.build_forecast(passports, costs, adjustments, None, "Бизнес", 1000.0)

    assert round(forecast["total"], 2) == round(120_000.0 * 1.21, 2)


def test_horizon_grows_the_estimate_to_the_year_of_signing_and_adds_the_increase():
    passports, costs = _forecast_base()
    summary = {f"p{i}": _summary_row(100.0, 20.0) for i in range(6)}
    adjustments = comparison.Adjustments(inflation=10.0, target_year=2024)
    for passport in passports.values():
        passport["year_signed"] = 2024

    forecast = history_check.build_forecast(
        passports, costs, adjustments, summary, "Бизнес", 1000.0, 5.0, 20.0,
    )

    columns = forecast["horizon"]["columns"]
    assert [column["year"] for column in columns] == [2024, 2025, 2026, 2027]
    assert columns[0]["estimate_display"] == forecast["total_display"] == "120 000 ₽"
    assert columns[0]["final_display"] == forecast["final_display"] == "144 000 ₽"
    assert columns[2]["estimate_display"] == "145 200 ₽"     # 120 000 × 1,1²
    assert columns[2]["increase_display"] == "29 040 ₽"      # 20 % к смете того года
    assert columns[2]["final_display"] == "174 240 ₽"
    assert columns[2]["low_display"] == "158 760 ₽"          # 120 000 × 1,05² × 1,2
    assert columns[2]["high_display"] == "207 360 ₽"         # 120 000 × 1,2² × 1,2
    assert columns[2]["growth_display"] == "+21,0 %"


def test_horizon_without_increase_data_carries_the_estimate_alone():
    passports, costs = _forecast_base()
    adjustments = comparison.Adjustments(inflation=10.0, target_year=2024)
    for passport in passports.values():
        passport["year_signed"] = 2024

    horizon = history_check.build_forecast(
        passports, costs, adjustments, None, "Бизнес", 1000.0,
    )["horizon"]

    assert horizon["has_increase"] is False
    assert horizon["columns"][1]["final_display"] == horizon["columns"][1]["estimate_display"]
    assert horizon["columns"][1]["estimate_display"] == "132 000 ₽"


def test_weighted_quantile_matches_the_plain_median_for_equal_weights():
    pairs = [(value, 1.0) for value in (10.0, 20.0, 30.0, 40.0)]

    assert history_check._weighted_quantile(pairs, 0.5) == 25.0
    assert history_check._weighted_quantile(pairs[:3], 0.5) == 20.0
    assert history_check._weighted_quantile([(5.0, 1.0)], 0.25) == 5.0
    assert history_check._weighted_quantile([], 0.5) is None


def test_weighted_quantile_follows_the_heavier_values():
    pairs = [(10.0, 1.0), (20.0, 1.0), (100.0, 10.0)]

    assert history_check._weighted_quantile(pairs, 0.5) > 60.0


# --- зоны риска: где ждать удорожание ---

def test_risk_zones_rank_work_types_by_the_money_they_usually_add():
    passports, costs = _forecast_base()
    summary = {f"p{i}": _summary_row(100.0, 20.0) for i in range(6)}
    # Фасад дорожает на 20 % у всех, кровля — на 10 % у одного из шести.
    increase = {f"p{i}": {"facade": 20_000.0} for i in range(6)}
    increase["p0"]["roof"] = 2_000.0

    forecast = history_check.build_forecast(
        passports, costs, OFF, summary, "Бизнес", 1000.0, increase_by_slug=increase,
    )

    risks = forecast["risks"]
    assert [row["key"] for row in risks] == ["facade", "roof"]
    assert risks[0]["grew_display"] == "6 из 6"
    assert risks[0]["typical_display"] == "+20,0 %"
    assert risks[0]["level"] == "alert"
    # Всё типичное удорожание класса (20 % от 120 000) приходится на фасад.
    assert risks[0]["amount_display"] == forecast["increase_display"] == "24 000 ₽"
    assert risks[1]["grew_display"] == "1 из 6"
    assert risks[1]["level"] == "ok"
    assert forecast["risk_objects"] == 6
    assert forecast["risk_alert_count"] == 1


def test_risk_zones_count_only_objects_with_increase_data():
    passports, costs = _forecast_base()
    increase = {f"p{i}": {"facade": 30_000.0} for i in range(3)}

    forecast = history_check.build_forecast(
        passports, costs, OFF, None, "Бизнес", 1000.0, increase_by_slug=increase,
    )

    facade = forecast["risks"][0]
    assert facade["grew_display"] == "3 из 3"
    assert facade["level"] == "none"      # трёх объектов мало для вывода
    assert forecast["risk_objects"] == 3


def test_forecast_without_increase_by_work_type_has_no_risk_zones():
    passports, costs = _forecast_base()

    forecast = history_check.build_forecast(passports, costs, OFF, None, "Бизнес", 1000.0)

    assert forecast["risks"] == []


def test_work_types_show_what_they_cost_with_the_extras():
    passports, costs = _forecast_base()
    summary = {f"p{i}": _summary_row(100.0, 20.0) for i in range(6)}
    increase = {f"p{i}": {"facade": 20_000.0} for i in range(6)}

    forecast = history_check.build_forecast(
        passports, costs, OFF, summary, "Бизнес", 1000.0, increase_by_slug=increase,
    )

    works = {row["key"]: row for row in forecast["works"]}
    assert forecast["has_extra"] is True
    assert works["facade"]["extra_display"] == "24 000 ₽"
    assert works["facade"]["with_extra_display"] == "124 000 ₽"
    assert works["roof"]["with_extra_display"] == "20 000 ₽"
    # Вместе виды работ дают итоговую стоимость: 124 000 + 20 000.
    assert forecast["final_display"] == "144 000 ₽"


def test_an_extra_every_object_pays_is_named_a_steady_one():
    passports, costs = _forecast_base()
    # Фасад дорожает у всех на 18–22 %, кровля — у двух из шести.
    increase = {f"p{i}": {"facade": 18_000.0 + 800.0 * i} for i in range(6)}
    increase["p0"]["roof"] = 10_000.0
    increase["p1"]["roof"] = 1_000.0

    forecast = history_check.build_forecast(
        passports, costs, OFF, None, "Бизнес", 1000.0, increase_by_slug=increase,
    )

    kinds = {row["key"]: row["kind"] for row in forecast["risks"]}
    assert kinds == {"facade": "постоянная добавка", "roof": "обычно не дорожает"}
    assert forecast["steady_count"] == 1


# --- статус «Завершён»: удорожание объекта в работе ещё не всё ---

def _with_status(count_done, count_open, done_share, open_share):
    passports, costs, summary, increase = {}, {}, {}, {}
    for i in range(count_done + count_open):
        slug = f"p{i}"
        done = i < count_done
        passports[slug] = _passport(f"Объект {i}")
        passports[slug]["completed"] = done
        costs[slug] = {"facade": 100_000.0, "roof": 20_000.0}
        share = done_share if done else open_share
        summary[slug] = _summary_row(120.0, 120.0 * share / 100.0)
        increase[slug] = {"facade": 120_000.0 * share / 100.0}
    return passports, costs, summary, increase


def test_increase_is_taken_from_completed_objects_when_there_are_enough():
    passports, costs, summary, increase = _with_status(4, 6, 30.0, 10.0)

    forecast = history_check.build_forecast(
        passports, costs, OFF, summary, "Бизнес", 1000.0, increase_by_slug=increase,
    )

    assert forecast["increase_completed_only"] is True
    assert forecast["increase_share_display"] == "30,0 %"
    assert forecast["increase_count"] == 4
    # По всем десяти, вместе с объектами в работе, вышло бы 10 %.
    assert forecast["increase_all_share_display"] == "10,0 %"
    assert forecast["increase_all_count"] == 10
    assert forecast["risk_objects"] == 4
    assert forecast["risks"][0]["grew_display"] == "4 из 4"
    # Смета от статуса не зависит — по всем десяти объектам.
    assert forecast["training_count"] == 10
    assert sum(1 for row in forecast["analogs"] if row["completed"]) == 4


def test_with_few_completed_objects_the_increase_falls_back_to_all_of_them():
    passports, costs, summary, increase = _with_status(3, 5, 30.0, 10.0)

    forecast = history_check.build_forecast(
        passports, costs, OFF, summary, "Бизнес", 1000.0, increase_by_slug=increase,
    )

    assert forecast["increase_completed_only"] is False
    assert forecast["increase_completed_count"] == 3
    assert forecast["increase_count"] == 8
    assert forecast["increase_share_display"] == "10,0 %"
    assert forecast["risk_objects"] == 8


# --- сравнение нового объекта с ближайшим объектом класса ---

def _reference_base():
    passports, costs = {}, {}
    for slug, area, year in (
        ("old", 100_000.0, 2020), ("fresh", 130_000.0, 2025),
        ("close", 101_000.0, 2022), ("far", 400_000.0, 2026),
        ("p4", 90_000.0, 2019), ("p5", 95_000.0, 2018),
    ):
        passport = _passport(slug, area=area)
        passport["year_signed"] = year
        passport["aboveground_area_sqm"] = area * 0.8
        passports[slug] = passport
        costs[slug] = {"facade": area * 100.0, "roof": area * 20.0}
    metrics = {
        slug: {"concrete_volume": passports[slug]["total_area_sqm"] * 0.5,
               "facade_area": passports[slug]["aboveground_area_sqm"] * 0.8}
        for slug in passports
    }
    return passports, costs, metrics


def test_the_reference_object_is_the_latest_among_those_close_in_area():
    passports, costs, metrics = _reference_base()

    forecast = history_check.build_forecast(
        passports, costs, OFF, None, "Бизнес", 100_000.0, metrics_by_slug=metrics,
    )

    reference = forecast["reference"]
    # «far» свежее, но вчетверо больше; из близких по площади свежее всех «fresh».
    assert reference["slug"] == "fresh"
    assert reference["near"] is True
    assert reference["year"] == 2025


def test_without_objects_close_in_area_the_nearest_one_is_taken():
    passports, costs, metrics = _reference_base()

    forecast = history_check.build_forecast(
        passports, costs, OFF, None, "Бизнес", 1_000_000.0, metrics_by_slug=metrics,
    )

    assert forecast["reference"]["slug"] == "far"
    assert forecast["reference"]["near"] is False


def test_the_new_object_is_compared_by_concrete_and_facade_per_square_metre():
    passports, costs, metrics = _reference_base()

    forecast = history_check.build_forecast(
        passports, costs, OFF, None, "Бизнес", 100_000.0, metrics_by_slug=metrics,
        new_object={
            "aboveground_area": 80_000.0,
            "concrete_volume": 65_000.0,   # 0,65 м³/м² против 0,5 у объекта сравнения
            "facade_area": 67_200.0,       # 0,84 м²/м² против 0,8
        },
    )

    rows = {row["key"]: row for row in forecast["reference"]["rows"]}
    assert rows["concrete_per"]["new_display"] == "0,650"
    assert rows["concrete_per"]["reference_display"] == "0,500"
    assert rows["concrete_per"]["difference_display"] == "+30,0 %"
    assert rows["concrete_per"]["level"] == "alert"
    assert rows["concrete_per"]["class_display"] == "0,500"
    assert rows["facade_per"]["difference_display"] == "+5,0 %"
    assert rows["facade_per"]["level"] == "ok"
    assert forecast["reference"]["has_new_figures"] is True
    assert forecast["reference"]["alert_count"] == 1


def test_without_figures_of_the_new_object_the_reference_is_still_shown():
    passports, costs, metrics = _reference_base()

    forecast = history_check.build_forecast(
        passports, costs, OFF, None, "Бизнес", 100_000.0, metrics_by_slug=metrics,
    )

    rows = {row["key"]: row for row in forecast["reference"]["rows"]}
    assert forecast["reference"]["has_new_figures"] is False
    assert rows["concrete_per"]["new_display"] == "—"
    assert rows["concrete_per"]["reference_display"] == "0,500"
    assert rows["concrete_per"]["level"] == "none"


def test_among_close_objects_one_with_concrete_and_facade_figures_is_preferred():
    passports, costs, metrics = _reference_base()
    metrics["fresh"] = {"concrete_volume": None, "facade_area": None}

    forecast = history_check.build_forecast(
        passports, costs, OFF, None, "Бизнес", 100_000.0, metrics_by_slug=metrics,
    )

    # «fresh» свежее, но сравнивать с ним нечего — берётся следующий по году.
    assert forecast["reference"]["slug"] == "close"
