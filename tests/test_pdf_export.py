import io

import pdfplumber

from app import passport as passport_module, pdf_export


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


def test_the_facts_table_carries_the_concrete_and_rebar_coefficients():
    passports = {"a": {
        "project_name": "ПроектА", "address": "г. Москва",
        "year_signed": "2024", "building_class": "Бизнес",
        "general_contractor": "ООО «Ромашка»", "contract_price_rub": 1_000_000_000.0,
        "underground_area_sqm": 1_000.0, "aboveground_area_sqm": 9_000.0,
        "total_area_sqm": 10_000.0, "rebar_coefficient_avg": 120.5,
    }}
    pdf_bytes = pdf_export.build_compare_pdf(
        passports, ["a"],
        passport_module.PASSPORT_FIELDS, passport_module.FIELD_LABELS, charts={},
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        price_per_sqm=passport_module.price_per_sqm,
        concrete_coefficients={"a": 0.5},
    )

    text = _page_texts(pdf_bytes)[0]

    assert "Коэффициент монолита" in text
    assert "Коэффициент арматуры" in text
    assert passport_module.format_number(0.5) in text
    assert passport_module.format_number(120.5) in text
