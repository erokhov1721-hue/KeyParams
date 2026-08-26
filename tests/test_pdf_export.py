import io

import pdfplumber

from app import comparison, cost_increase, passport as passport_module, pdf_export
from app.comparison import Adjustments

NONE = Adjustments()


def _page_texts(pdf_bytes):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _build(**kwargs):
    passports = {"a": {
        "project_name": "ПроектА", "address": "г. Москва",
        "year_signed": "2024", "building_class": "Бизнес",
        "general_contractor": "ООО «Ромашка»", "contract_price_rub": 1_000_000_000.0,
        "underground_area_sqm": 1_000.0, "aboveground_area_sqm": 9_000.0,
        "total_area_sqm": 10_000.0,
    }}
    charts = {"price_by_year": [
        {"label": "ПроектА (2024)", "value": 1_000_000_000.0,
         "display": "1 000 000 000", "width_pct": 100.0},
    ]}
    return pdf_export.build_compare_pdf(
        passports, ["a"],
        passport_module.PASSPORT_FIELDS, passport_module.FIELD_LABELS, charts,
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        price_per_sqm=passport_module.price_per_sqm,
        **kwargs,
    )


def test_the_charts_start_on_a_page_of_their_own():
    # Первая диаграмма ютилась под таблицами внизу первой страницы, а
    # остальные уезжали на следующую — читать такое приходилось вразбивку.
    pages = _page_texts(_build())

    assert "Общие сведения" in pages[0]
    assert "Цена работ по году подписания договора" not in pages[0]
    assert "Цена работ по году подписания договора" in pages[1]


def test_the_tables_stay_on_the_first_page():
    terms = {"rows": [
        {"field": "smr_term", "label": "Срок СМР", "cells": ["33 мес"]},
    ]}

    pages = _page_texts(_build(terms=terms))

    assert "Сравнение проектов" in pages[0]
    assert "Общие сведения" in pages[0]
    assert "Условия" in pages[0]
    assert "Срок СМР" in pages[0]


def test_the_facts_table_has_no_coefficient_rows():
    # Коэффициенты бетона, фасада и арматуры живут только в своих графиках —
    # таблица фактов их не дублирует.
    text = _page_texts(_build())[0]

    assert "Коэффициент монолита" not in text
    assert "Коэффициент фасада" not in text
    assert "Коэффициент арматуры" not in text


def test_the_charts_include_the_concrete_facade_and_rebar_coefficients():
    passports = {"a": {
        "project_name": "ПроектА", "address": None, "year_signed": None,
        "building_class": None, "general_contractor": None,
        "contract_price_rub": None, "underground_area_sqm": None,
        "aboveground_area_sqm": None, "total_area_sqm": 1_000.0,
        "rebar_coefficient_avg": 120.5,
    }}
    charts = passport_module.build_comparison_charts(
        passports, ["a"],
        concrete_coefficients={"a": 0.5}, facade_coefficients={"a": 2.5},
    )
    pdf_bytes = pdf_export.build_compare_pdf(
        passports, ["a"],
        passport_module.PASSPORT_FIELDS, passport_module.FIELD_LABELS, charts,
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        price_per_sqm=passport_module.price_per_sqm,
    )

    # Диаграммы начинаются со второй страницы (первая — «Общие сведения»).
    charts_text = "\n".join(_page_texts(pdf_bytes)[1:])
    assert "Коэффициент монолита" in charts_text
    assert "Коэффициент фасада" in charts_text
    assert "Коэффициент арматуры" in charts_text


def _increase_report(rows):
    """Отчёт по удорожанию из готовых строк (название, было, стало) — тем же
    ``build_report``, что и в тестах ``comparison``: подделка данных здесь
    ничего не проверяла бы, если правило расчёта увеличения изменится."""
    lines = [cost_increase.Line(name, was, now) for name, was, now in rows]
    return cost_increase.build_report(lines)


def _increase_pdf():
    """PDF с блоком «Удорожание проектов» — площадь известна, поэтому три
    плитки (включая ₽/м²), и три вида работ гарантированно в отчёте."""
    passports = {"a": {"project_name": "ПроектА", "year_signed": "2024",
                       "total_area_sqm": 1_000.0}}
    charts = {"price_by_year": [
        {"label": "ПроектА (2024)", "value": 1_000_000_000.0,
         "display": "1 000 000 000", "width_pct": 100.0},
    ]}
    increase = comparison.build_increase_summary(
        ["a"], passports,
        {"a": _increase_report([
            ("Кровля", 100_000.0, 130_000.0),
            ("Фасадные работы", 100_000.0, 250_000.0),
            ("Котлован", 100_000.0, 90_000.0),
        ])},
        NONE,
    )
    pdf_bytes = pdf_export.build_compare_pdf(
        passports, ["a"],
        passport_module.PASSPORT_FIELDS, passport_module.FIELD_LABELS, charts,
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        price_per_sqm=passport_module.price_per_sqm,
        increase=increase,
    )
    return pdf_bytes, increase


def _find_increase_page(pdf):
    for page in pdf.pages:
        if "Удорожание проектов" in (page.extract_text() or ""):
            return page
    raise AssertionError("страница с блоком «Удорожание проектов» не найдена")


def test_the_kpi_tile_number_does_not_overlap_its_caption():
    # 16pt цифра рисовалась в абзаце с leading под 12pt: цифра наезжала на
    # подпись под ней вместо того, чтобы кончаться выше неё.
    pdf_bytes, _ = _increase_pdf()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = _find_increase_page(pdf)
        words = page.extract_words()
        value = next(
            w for w in words
            if w["top"] < 120 and (w["text"].startswith("+") or w["text"].startswith("−"))
        )
        caption = next(w for w in words if w["text"] == "Средний")
        assert value["bottom"] <= caption["top"]


def test_the_kpi_tiles_have_borders():
    # Таблица плиток не рисовала ни BOX, ни BACKGROUND — рамки не было вовсе.
    pdf_bytes, increase = _increase_pdf()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = _find_increase_page(pdf)
        tile_backgrounds = [r for r in page.rects if r["top"] < 120]
        assert len(tile_backgrounds) >= 3  # три плитки: %, сумма, ₽/м²


def test_the_work_rows_draw_progress_bars():
    # Строки таблицы видов работ собирались только из текста — ни «дорожает
    # в», ни «всего удорожания» не рисовали свою полоску, хотя данные для неё
    # уже посчитаны (frequency_pct, width_pct).
    pdf_bytes, increase = _increase_pdf()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = _find_increase_page(pdf)
        # Трек со скруглёнными углами — путь с кривыми, а не прямоугольник:
        # pdfplumber видит такие фигуры в ``curves``, не в ``rects``. Трек
        # рисуется всегда, даже при нулевой доле — минимум два таких пути на
        # строку (частота и дельта).
        assert len(page.curves) >= 2 * len(increase["works"])
