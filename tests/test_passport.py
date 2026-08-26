from app import ai_extractor, ocr, passport
from tests.helpers import document_xml, make_docx, words_from_text


def test_passport_fields_order():
    assert passport.PASSPORT_FIELDS == [
        "project_name", "address", "year_signed", "building_class",
        "general_contractor", "contract_price_rub", "underground_area_sqm",
        "aboveground_area_sqm", "total_area_sqm",
    ]


# --- format_number ---

def test_format_number_none_returns_none():
    assert passport.format_number(None) is None


def test_format_number_whole_number_has_no_decimals():
    assert passport.format_number(67413.0) == "67 413"


def test_format_number_groups_thousands():
    assert passport.format_number(10067050887.0) == "10 067 050 887"


def test_format_number_keeps_two_decimals_when_not_whole():
    assert passport.format_number(10067050887.72) == "10 067 050 887.72"


def test_format_number_small_value_no_grouping_needed():
    assert passport.format_number(500.0) == "500"


def test_format_number_leaves_non_numeric_string_untouched():
    assert passport.format_number("Бизнес") == "Бизнес"


def test_price_per_sqm_computed_from_price_and_total_area():
    data = {"contract_price_rub": 10067050887.72, "total_area_sqm": 67413.0}
    assert passport.price_per_sqm(data) == 10067050887.72 / 67413.0


def test_price_per_sqm_none_when_price_missing():
    data = {"contract_price_rub": None, "total_area_sqm": 67413.0}
    assert passport.price_per_sqm(data) is None


def test_price_per_sqm_none_when_area_missing():
    data = {"contract_price_rub": 10067050887.72, "total_area_sqm": None}
    assert passport.price_per_sqm(data) is None


def test_price_per_sqm_none_when_area_zero():
    data = {"contract_price_rub": 10067050887.72, "total_area_sqm": 0}
    assert passport.price_per_sqm(data) is None


# --- build_comparison_charts ---

def _passport(name, price=None, year=None, building_class=None, area=None, rebar=None):
    return {
        "project_name": name, "year_signed": year, "building_class": building_class,
        "general_contractor": None, "contract_price_rub": price,
        "underground_area_sqm": None, "aboveground_area_sqm": None,
        "total_area_sqm": area, "rebar_coefficient_avg": rebar, "ocr_fields": [],
    }


def test_charts_price_by_year_sorted_ascending_by_year():
    passports = {
        "b": _passport("Проект Б", price=200.0, year="2023"),
        "a": _passport("Проект А", price=100.0, year="2025"),
    }
    charts = passport.build_comparison_charts(passports, ["a", "b"])
    labels = [row["label"] for row in charts["price_by_year"]]
    assert labels == ["Проект Б (2023)", "Проект А (2025)"]


def test_charts_price_by_year_skips_project_without_year():
    passports = {
        "a": _passport("Проект А", price=100.0, year=None),
        "b": _passport("Проект Б", price=200.0, year="2023"),
    }
    charts = passport.build_comparison_charts(passports, ["a", "b"])
    assert [row["label"] for row in charts["price_by_year"]] == ["Проект Б (2023)"]


def test_charts_price_by_class_skips_project_without_class():
    passports = {
        "a": _passport("Проект А", price=100.0, building_class=None),
        "b": _passport("Проект Б", price=200.0, building_class="Бизнес"),
    }
    charts = passport.build_comparison_charts(passports, ["a", "b"])
    assert [row["label"] for row in charts["price_by_class"]] == ["Проект Б (Бизнес)"]


def test_charts_price_sorted_ascending_by_value():
    passports = {
        "a": _passport("Проект А", price=300.0),
        "b": _passport("Проект Б", price=100.0),
        "c": _passport("Проект В", price=200.0),
    }
    charts = passport.build_comparison_charts(passports, ["a", "b", "c"])
    assert [row["label"] for row in charts["price"]] == ["Проект Б", "Проект В", "Проект А"]


def test_charts_price_skips_project_without_price():
    passports = {
        "a": _passport("Проект А", price=None),
        "b": _passport("Проект Б", price=200.0),
    }
    charts = passport.build_comparison_charts(passports, ["a", "b"])
    assert [row["label"] for row in charts["price"]] == ["Проект Б"]


def test_charts_price_per_sqm_sorted_ascending():
    passports = {
        "a": _passport("Проект А", price=300.0, area=1.0),
        "b": _passport("Проект Б", price=100.0, area=1.0),
    }
    charts = passport.build_comparison_charts(passports, ["a", "b"])
    assert [row["label"] for row in charts["price_per_sqm"]] == ["Проект Б", "Проект А"]


def test_charts_price_computes_bar_width_relative_to_max():
    passports = {
        "a": _passport("Проект А", price=100.0),
        "b": _passport("Проект Б", price=50.0),
    }
    charts = passport.build_comparison_charts(passports, ["a", "b"])
    rows = {row["label"]: row for row in charts["price"]}
    assert rows["Проект Б"]["width_pct"] == 50.0
    assert rows["Проект А"]["width_pct"] == 100.0
    assert rows["Проект А"]["display"] == "100.00 ₽"


def test_charts_price_short_display_abbreviates_billions():
    passports = {"a": _passport("Проект А", price=24157917118.54)}
    charts = passport.build_comparison_charts(passports, ["a"])
    assert charts["price"][0]["short_display"] == "24.16 млрд ₽"


def test_charts_price_short_display_abbreviates_millions():
    passports = {"a": _passport("Проект А", price=3450000.0)}
    charts = passport.build_comparison_charts(passports, ["a"])
    assert charts["price"][0]["short_display"] == "3.45 млн ₽"


def test_charts_price_short_display_falls_back_to_full_below_a_thousand():
    passports = {"a": _passport("Проект А", price=500.0)}
    charts = passport.build_comparison_charts(passports, ["a"])
    assert charts["price"][0]["short_display"] == "500.00 ₽"


def test_charts_price_by_year_and_by_class_are_also_abbreviated_money():
    passports = {"a": _passport("Проект А", price=24157917118.54, year="2024")}
    charts = passport.build_comparison_charts(passports, ["a"])
    assert charts["price_by_year"][0]["short_display"] == "24.16 млрд ₽"


def test_charts_price_per_sqm_display_is_grouped_whole_roubles():
    passports = {
        "a": _passport("Проект А", price=138577.42 * 67413.0, area=67413.0),
    }
    charts = passport.build_comparison_charts(passports, ["a"])
    assert charts["price_per_sqm"][0]["display"] == "138 577 ₽"


def test_charts_coefficient_display_stays_two_decimals_no_currency():
    passports = {"a": _passport("Проект А")}
    charts = passport.build_comparison_charts(
        passports, ["a"], concrete_coefficients={"a": 0.6},
    )
    assert charts["concrete_coefficient"][0]["display"] == "0.60"


def test_charts_zero_value_row_is_flagged():
    passports = {"a": _passport("Проект А"), "b": _passport("Проект Б")}
    charts = passport.build_comparison_charts(
        passports, ["a", "b"], facade_coefficients={"a": 0.0, "b": 1.2},
    )
    rows = {row["label"]: row for row in charts["facade_coefficient"]}
    assert rows["Проект А"]["is_zero"] is True
    assert rows["Проект Б"]["is_zero"] is False


def test_charts_value_rounding_to_zero_display_is_also_flagged():
    # В реальных данных «0.00» на экране не всегда значит точный ноль —
    # площадь фасада может оказаться крошечной долей от общей площади и
    # округлиться до 0.00, а полоска при этом всё равно рисуется. Именно
    # так и выглядел баг, который правит эта карточка.
    passports = {"a": _passport("Проект А"), "b": _passport("Проект Б")}
    charts = passport.build_comparison_charts(
        passports, ["a", "b"], facade_coefficients={"a": 0.0026, "b": 1.2},
    )
    rows = {row["label"]: row for row in charts["facade_coefficient"]}
    assert rows["Проект А"]["display"] == "0.00"
    assert rows["Проект А"]["is_zero"] is True


# --- project_colors ---

def test_project_colors_assigns_first_two_from_the_fixed_palette():
    colors = passport.project_colors(["a", "b"])
    assert colors == {"a": "#059669", "b": "#4f46e5"}


def test_project_colors_keyed_by_position_not_alphabetical_order():
    colors = passport.project_colors(["b", "a"])
    assert colors["b"] == "#059669"
    assert colors["a"] == "#4f46e5"


def test_project_colors_rotates_the_palette_past_its_length():
    palette_len = len(passport.PROJECT_COLOR_PALETTE)
    slugs = [f"p{i}" for i in range(palette_len + 1)]
    colors = passport.project_colors(slugs)
    assert colors["p0"] == colors[f"p{palette_len}"]


def test_charts_price_per_sqm_skips_when_not_computable():
    passports = {
        "a": _passport("Проект А", price=300.0, area=None),
        "b": _passport("Проект Б", price=100.0, area=1.0),
    }
    charts = passport.build_comparison_charts(passports, ["a", "b"])
    assert [row["label"] for row in charts["price_per_sqm"]] == ["Проект Б"]


def test_charts_concrete_coefficient_sorted_ascending_and_skips_missing():
    passports = {
        "a": _passport("Проект А"),
        "b": _passport("Проект Б"),
        "c": _passport("Проект В"),
    }
    charts = passport.build_comparison_charts(
        passports, ["a", "b", "c"],
        concrete_coefficients={"a": 0.6, "c": 0.3},   # "b" has none — skipped
    )
    assert [row["label"] for row in charts["concrete_coefficient"]] == [
        "Проект В", "Проект А",
    ]


def test_charts_facade_coefficient_sorted_ascending_and_skips_missing():
    passports = {
        "a": _passport("Проект А"),
        "b": _passport("Проект Б"),
        "c": _passport("Проект В"),
    }
    charts = passport.build_comparison_charts(
        passports, ["a", "b", "c"],
        facade_coefficients={"a": 1.6, "c": 0.9},   # "b" has none — skipped
    )
    assert [row["label"] for row in charts["facade_coefficient"]] == [
        "Проект В", "Проект А",
    ]


def test_charts_rebar_coefficient_sorted_ascending_and_skips_missing():
    passports = {
        "a": _passport("Проект А", rebar=150.0),
        "b": _passport("Проект Б", rebar=None),
        "c": _passport("Проект В", rebar=110.0),
    }
    charts = passport.build_comparison_charts(passports, ["a", "b", "c"])
    assert [row["label"] for row in charts["rebar_coefficient"]] == [
        "Проект В", "Проект А",
    ]


def test_build_passport_fills_found_fields_and_nulls_missing(tmp_path):
    dgp_xml = document_xml(paragraphs=[
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,"
    ])
    tz_xml = document_xml(tables=[[["1", "Площадь подземной части", "м2", "1 000"]]])
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    result = passport.build_passport("Тестовый проект", dgp_path, tz_path)

    assert result["project_name"] == "Тестовый проект"
    assert result["general_contractor"] == "ООО «Ромашка»"
    assert result["underground_area_sqm"] == 1000.0
    assert result["building_class"] is None
    assert result["year_signed"] is None
    assert result["aboveground_area_sqm"] is None
    assert result["total_area_sqm"] is None


def test_save_and_load_passport_roundtrip(tmp_path):
    fields = passport.PASSPORT_FIELDS + passport.CONTRACT_FIELDS + [
        passport.REBAR_COEFFICIENT_FIELD, passport.FACADE_AREA_FIELD,
        passport.CONCRETE_VOLUME_FIELD,
    ]
    data = {field: None for field in fields}
    data["project_name"] = "Проспект Мира"
    data["general_contractor"] = "ООО «АНТТЕК»"
    path = tmp_path / "passport.json"
    passport.save_passport(data, path)
    loaded = passport.load_passport(path)
    assert loaded == data


def test_load_passport_backfills_missing_field_from_older_save(tmp_path):
    # A passport saved before contract_price_rub existed lacks the key —
    # load_passport must backfill it as None rather than raise/omit it, so
    # templates that iterate PASSPORT_FIELDS don't hit a missing key.
    path = tmp_path / "passport.json"
    passport.save_passport({"project_name": "Старый проект"}, path)
    loaded = passport.load_passport(path)
    assert loaded["contract_price_rub"] is None


def test_save_passport_writes_readable_utf8(tmp_path):
    data = {"project_name": "Проспект Мира"}
    path = tmp_path / "passport.json"
    passport.save_passport(data, path)
    text = path.read_text(encoding="utf-8")
    assert "Проспект Мира" in text


def test_build_passport_easyocr_disabled_by_default(tmp_path, monkeypatch):
    # EasyOCR is opt-in (OCR_FALLBACK_ENABLED=1) because it is CPU-only and
    # slow in this environment. With the env var unset and no fast engine to
    # be had, recognize_text must never be called, even when fields are
    # missing and images are present.
    monkeypatch.delenv(passport.OCR_FALLBACK_ENV_VAR, raising=False)
    calls = []
    monkeypatch.setattr(
        ocr, "recognize_text",
        lambda images: calls.append(images) or [""] * len(images),
    )
    dgp_xml = document_xml()
    tz_xml = document_xml()
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(
        tmp_path, tz_xml, "tz.docx",
        extra_files={"word/media/image1.png": b"fake-image-bytes"},
    )

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert calls == []
    assert result["ocr_fields"] == []
    assert result["total_area_sqm"] is None


def test_build_passport_uses_the_windows_engine_without_the_opt_in(tmp_path, monkeypatch):
    # The opt-in guards against EasyOCR's minutes, not against OCR as such:
    # where the fast engine exists it simply runs, and the slow one is left
    # alone.
    monkeypatch.delenv(passport.OCR_FALLBACK_ENV_VAR, raising=False)
    monkeypatch.setattr(passport.win_ocr, "available", lambda: True)
    monkeypatch.setattr(
        passport.win_ocr, "recognize_text",
        lambda images: ["Общая площадь м2 67 413"] * len(images),
    )
    slow_calls = []
    monkeypatch.setattr(
        ocr, "recognize_text", lambda images: slow_calls.append(images) or [],
    )
    dgp_path = make_docx(tmp_path, document_xml(), "dgp.docx")
    tz_path = make_docx(
        tmp_path, document_xml(), "tz.docx",
        extra_files={"word/media/image1.png": b"fake-image-bytes"},
    )

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["total_area_sqm"] == 67413.0
    assert result["ocr_fields"] == ["total_area_sqm"]
    assert slow_calls == [], "медленный распознаватель не трогаем, есть быстрый"


def test_build_passport_ocr_fallback_fills_area_from_image(tmp_path, monkeypatch):
    # OCR сам по себе не тестируется здесь (см. tests/test_ocr.py и ручную
    # проверку на реальном файле) — только то, что passport.py правильно
    # применяет резерв и помечает поле как заполненное через OCR.
    monkeypatch.setenv(passport.OCR_FALLBACK_ENV_VAR, "1")
    monkeypatch.setattr(
        ocr, "recognize_text",
        lambda images: ["Общая площадь м2 67 413"] * len(images),
    )
    dgp_xml = document_xml(paragraphs=[
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,"
    ])
    tz_xml = document_xml()
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(
        tmp_path, tz_xml, "tz.docx",
        extra_files={"word/media/image1.png": b"fake-image-bytes"},
    )

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["total_area_sqm"] == 67413.0
    assert result["ocr_fields"] == ["total_area_sqm"]
    # Поля, которых распознанный текст не касается, остаются пустыми:
    assert result["underground_area_sqm"] is None
    assert result["aboveground_area_sqm"] is None


def test_build_passport_ocr_fallback_disambiguates_footprint_from_underground(tmp_path, monkeypatch):
    # OCR text contains both the building-footprint row ("Площадь застройки
    # подземной части") and the real target row ("Общая площадь подземного
    # паркинга"). The fallback must pick the latter, not the first match.
    monkeypatch.setenv(passport.OCR_FALLBACK_ENV_VAR, "1")
    monkeypatch.setattr(
        ocr, "recognize_text",
        lambda images: [
            "Площадь застройки подземной части м2 4 611\n"
            "Общая площадь подземного паркинга м2 13 297"
        ] * len(images),
    )
    dgp_xml = document_xml()
    tz_xml = document_xml()
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(
        tmp_path, tz_xml, "tz.docx",
        extra_files={"word/media/image1.png": b"fake-image-bytes"},
    )

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["underground_area_sqm"] == 13297.0
    assert result["ocr_fields"] == ["underground_area_sqm"]


def test_build_passport_skips_ocr_when_nothing_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ocr, "recognize_text",
        lambda images: calls.append(images) or [""] * len(images),
    )
    # Every one of the 6 fields is resolvable from ordinary text/tables, so
    # the OCR fallback's "if not missing: return []" guard should fire
    # before recognize_text is ever called — even though the DGP has an
    # attached image, proving the fallback is lazy, not eager.
    dgp_xml = document_xml(paragraphs=[
        "г. Москва",
        "«04» февраля 2025 г.",
        "Жилой комплекс бизнес-класса.",
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,",
    ])
    tz_xml = document_xml(tables=[[
        ["1", "Площадь подземной части", "м2", "1 000"],
        ["2", "Площадь надземной части", "м2", "2 000"],
        ["3", "Общая площадь", "м2", "3 000"],
    ]])
    dgp_path = make_docx(
        tmp_path, dgp_xml, "dgp.docx",
        extra_files={"word/media/image1.png": b"unused-because-nothing-is-missing"},
    )
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["ocr_fields"] == []
    assert calls == []


def test_build_passport_ai_fallback_fills_missing_field(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ai_extractor, "extract_missing_fields",
        lambda missing_fields, context_text: {"general_contractor": "ООО «Тест»"},
    )
    dgp_xml = document_xml()  # no general_contractor phrase anywhere
    tz_xml = document_xml(tables=[[["Общая площадь", "67413", "м2"]]])
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["general_contractor"] == "ООО «Тест»"
    assert result["ai_fields"] == ["general_contractor"]


def test_build_passport_ai_fallback_skipped_when_nothing_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ai_extractor, "extract_missing_fields",
        lambda missing_fields, context_text: calls.append(missing_fields) or {},
    )
    dgp_xml = document_xml(paragraphs=[
        "г. Москва",
        "«04» февраля 2025 г.",
        "Жилой комплекс бизнес-класса.",
        "Объект, расположенный по адресу: г. Москва, ул. Верейская, вл. 29/35.",
        "Цена Работ по настоящему Договору составляет 10 067 050 887,72 руб., включая НДС.",
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,",
    ])
    tz_xml = document_xml(tables=[[
        ["1", "Площадь подземной части", "м2", "1 000"],
        ["2", "Площадь надземной части", "м2", "2 000"],
        ["3", "Общая площадь", "м2", "3 000"],
    ]])
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["ai_fields"] == []
    assert calls == []


def test_build_passport_ai_fallback_failure_leaves_fields_none(tmp_path, monkeypatch):
    # Mirrors how the OCR fallback degrades on failure: extract_missing_fields
    # is contracted to never raise, returning {} on any internal error, so
    # build_passport just sees "nothing found" and keeps going.
    monkeypatch.setattr(
        ai_extractor, "extract_missing_fields",
        lambda missing_fields, context_text: {},
    )
    dgp_xml = document_xml()
    tz_xml = document_xml()
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["ai_fields"] == []
    assert result["total_area_sqm"] is None


def test_build_passport_ai_context_includes_ocr_text_when_ocr_ran(tmp_path, monkeypatch):
    monkeypatch.setenv(passport.OCR_FALLBACK_ENV_VAR, "1")
    monkeypatch.setattr(
        ocr, "recognize_text",
        lambda images: ["Генподрядчик ООО «Из Картинки»"] * len(images),
    )
    captured = {}

    def fake_extract(missing_fields, context_text):
        captured["context_text"] = context_text
        return {}

    monkeypatch.setattr(ai_extractor, "extract_missing_fields", fake_extract)

    dgp_xml = document_xml()
    tz_xml = document_xml()
    dgp_path = make_docx(
        tmp_path, dgp_xml, "dgp.docx",
        extra_files={"word/media/image1.png": b"fake-image-bytes"},
    )
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    passport.build_passport("Тест", dgp_path, tz_path)

    assert "Из Картинки" in captured["context_text"]


def test_build_passport_ocr_failure_leaves_field_none(tmp_path, monkeypatch):
    monkeypatch.setenv(passport.OCR_FALLBACK_ENV_VAR, "1")
    monkeypatch.setattr(ocr, "recognize_text", lambda images: [""] * len(images))
    dgp_xml = document_xml()
    tz_xml = document_xml()
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(
        tmp_path, tz_xml, "tz.docx",
        extra_files={"word/media/image1.png": b"fake-image-bytes"},
    )

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["total_area_sqm"] is None
    assert result["ocr_fields"] == []


def test_build_passport_ocr_skips_tz_when_only_dgp_field_missing(tmp_path, monkeypatch):
    # Only a DGP-only field (general_contractor) is missing;
    # building_class and all area fields are resolved normally.
    # The OCR fallback should OCR dgp.images but NOT tz.images, proving
    # needs_tz_ocr correctly scopes to TZ-sourced fields only.
    monkeypatch.setenv(passport.OCR_FALLBACK_ENV_VAR, "1")
    dgp_calls = []
    tz_calls = []

    def mock_recognize(images):
        # Record which file's images were OCR'd based on marker in bytes
        if images and len(images) > 0:
            if b"dgp-image" in images[0]:
                dgp_calls.append(images)
            elif b"tz-image" in images[0]:
                tz_calls.append(images)
        return [""] * len(images)

    monkeypatch.setattr(ocr, "recognize_text", mock_recognize)

    # DGP: has year_signed and building_class clues, but NOT general_contractor
    dgp_xml = document_xml(paragraphs=[
        "г. Москва",
        "«04» февраля 2025 г.",
        "Жилой комплекс бизнес-класса.",
    ])
    # TZ: has all area values
    tz_xml = document_xml(tables=[[
        ["1", "Площадь подземной части", "м2", "1 000"],
        ["2", "Площадь надземной части", "м2", "2 000"],
        ["3", "Общая площадь", "м2", "3 000"],
    ]])
    dgp_path = make_docx(
        tmp_path, dgp_xml, "dgp.docx",
        extra_files={"word/media/image1.png": b"dgp-image-bytes"},
    )
    tz_path = make_docx(
        tmp_path, tz_xml, "tz.docx",
        extra_files={"word/media/image1.png": b"tz-image-bytes"},
    )

    result = passport.build_passport("Тест", dgp_path, tz_path)

    # All TZ fields and building_class found normally, general_contractor missing
    assert result["underground_area_sqm"] == 1000.0
    assert result["aboveground_area_sqm"] == 2000.0
    assert result["total_area_sqm"] == 3000.0
    assert result["building_class"] is not None  # Found from DGP/TZ
    assert result["year_signed"] is not None  # Found from DGP
    assert result["general_contractor"] is None
    assert result["ocr_fields"] == []
    # Verify TZ images were NOT OCR'd (only DGP field is missing)
    assert tz_calls == [], "TZ images should not be OCR'd when only DGP fields are missing"


# --- build_contract_terms: says why nothing was filled ---

_PROTOCOL_TEXT = """Протокол окончательных условий
1 Срок выполнения СМР и MR Base, месяц
30 месяца, с даты передачи первой захватки до даты получения ЗОС
3 Аванс, % 30% максимальная сумма не закрытого аванса 20%
4 Банковская гарантия на возврат аванса Не включено - 90 134 910,00 руб.
5 Performance bond, % 3%
"""


def _stub_pdf(monkeypatch, text, images=(), ocr_texts=()):
    monkeypatch.setattr(passport.pdf_reader, "read_pdf_text", lambda path: text)
    monkeypatch.setattr(
        passport.pdf_reader, "render_pages_to_images",
        lambda path, **kwargs: list(images),
    )
    # Local OCR is stubbed by default: it is the last-resort path for a scan,
    # and letting the real one run would load the recognition model into every
    # test that touches a scanned protocol. Windows' engine is switched off
    # here so these tests read the same on a machine that has it and one that
    # doesn't; the ordering between the two engines is tested on its own.
    monkeypatch.setattr(passport.win_ocr, "available", lambda: False)
    monkeypatch.setattr(
        passport.ocr, "recognize_page_words",
        lambda image: words_from_text("\n".join(ocr_texts)),
    )


def test_build_contract_terms_text_layer_fills_fields_with_no_problem(monkeypatch):
    _stub_pdf(monkeypatch, _PROTOCOL_TEXT)

    data, filled, problem = passport.build_contract_terms("ignored.pdf")

    assert data["performance_bond_pct"] == "3%"
    assert data["bank_guarantee"] == "Не включено"
    assert "smr_term" in filled
    assert problem is None


def test_build_contract_terms_text_layer_without_matches_reports_nothing_found(monkeypatch):
    _stub_pdf(monkeypatch, "Совершенно посторонний текст без условий договора.")

    data, filled, problem = passport.build_contract_terms("ignored.pdf")

    assert filled == []
    assert problem == passport.CONTRACT_PROBLEM_NOTHING_FOUND


def test_build_contract_terms_scan_propagates_missing_key_problem(monkeypatch):
    _stub_pdf(monkeypatch, "", images=[b"png"])
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({}, passport.ai_extractor.PROBLEM_NO_KEY),
    )

    data, filled, problem = passport.build_contract_terms("ignored.pdf")

    assert filled == []
    assert problem == passport.ai_extractor.PROBLEM_NO_KEY


def test_build_contract_terms_scan_propagates_no_credit_problem(monkeypatch):
    _stub_pdf(monkeypatch, "", images=[b"png"])
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({}, passport.ai_extractor.PROBLEM_NO_CREDIT),
    )

    _data, _filled, problem = passport.build_contract_terms("ignored.pdf")

    assert problem == passport.ai_extractor.PROBLEM_NO_CREDIT


def test_build_contract_terms_scan_success_keeps_vat_from_recognition(monkeypatch):
    _stub_pdf(monkeypatch, "", images=[b"png"])
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({"performance_bond_pct": "3%", "vat": "20%"}, None),
    )

    data, filled, problem = passport.build_contract_terms("ignored.pdf")

    assert data["vat"] == "20%"
    assert "vat" in filled
    assert problem is None


def test_build_contract_terms_falls_back_to_local_ocr_when_the_api_is_unavailable(monkeypatch):
    _stub_pdf(monkeypatch, "", images=[b"png"], ocr_texts=[_PROTOCOL_TEXT])
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({}, passport.ai_extractor.PROBLEM_NO_CREDIT),
    )

    data, filled, problem = passport.build_contract_terms("ignored.pdf")

    assert data["performance_bond_pct"] == "3%"
    assert data["bank_guarantee"] == "Не включено"
    assert "smr_term" in filled
    # The API failure stops being worth reporting once the card is filled.
    assert problem is None


def test_build_contract_terms_local_ocr_is_not_used_when_the_api_succeeds(monkeypatch):
    calls = []
    _stub_pdf(monkeypatch, "", images=[b"png"])
    monkeypatch.setattr(
        passport.ocr, "recognize_text", lambda images: calls.append(images) or [],
    )
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({"performance_bond_pct": "3%"}, None),
    )

    _data, _filled, problem = passport.build_contract_terms("ignored.pdf")

    assert problem is None
    assert calls == [], "минуты на распознавание не тратятся, если API ответил"


def test_build_contract_terms_keeps_the_api_problem_when_ocr_reads_nothing(monkeypatch):
    _stub_pdf(monkeypatch, "", images=[b"png"], ocr_texts=[""])
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({}, passport.ai_extractor.PROBLEM_NO_KEY),
    )

    _data, filled, problem = passport.build_contract_terms("ignored.pdf")

    assert filled == []
    assert problem == passport.ai_extractor.PROBLEM_NO_KEY


def test_build_contract_terms_keeps_the_api_problem_when_ocr_finds_no_conditions(monkeypatch):
    _stub_pdf(
        monkeypatch, "", images=[b"png"],
        ocr_texts=["Совершенно посторонний распознанный текст."],
    )
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({}, passport.ai_extractor.PROBLEM_NO_CREDIT),
    )

    _data, filled, problem = passport.build_contract_terms("ignored.pdf")

    assert filled == []
    assert problem == passport.ai_extractor.PROBLEM_NO_CREDIT


def test_build_contract_terms_prefers_the_windows_engine_over_easyocr(monkeypatch):
    _stub_pdf(monkeypatch, "", images=[b"png"])
    slow_calls = []
    monkeypatch.setattr(passport.win_ocr, "available", lambda: True)
    monkeypatch.setattr(
        passport.win_ocr, "recognize_page_words",
        lambda image: words_from_text(_PROTOCOL_TEXT),
    )
    monkeypatch.setattr(
        passport.ocr, "recognize_page_words",
        lambda image: slow_calls.append(image) or [],
    )
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({}, passport.ai_extractor.PROBLEM_NO_CREDIT),
    )

    data, _filled, problem = passport.build_contract_terms("ignored.pdf")

    assert data["performance_bond_pct"] == "3%"
    assert problem is None
    assert slow_calls == [], "медленный распознаватель не запускается, если быстрый справился"


def test_build_contract_terms_falls_back_to_easyocr_when_windows_reads_nothing(monkeypatch):
    _stub_pdf(monkeypatch, "", images=[b"png"])
    monkeypatch.setattr(passport.win_ocr, "available", lambda: True)
    monkeypatch.setattr(passport.win_ocr, "recognize_page_words", lambda image: [])
    monkeypatch.setattr(
        passport.ocr, "recognize_page_words",
        lambda image: words_from_text(_PROTOCOL_TEXT),
    )
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({}, passport.ai_extractor.PROBLEM_NO_CREDIT),
    )

    data, _filled, problem = passport.build_contract_terms("ignored.pdf")

    assert data["performance_bond_pct"] == "3%"
    assert problem is None


def test_every_contract_problem_code_has_a_russian_message():
    codes = [
        passport.CONTRACT_PROBLEM_NOTHING_FOUND,
        passport.ai_extractor.PROBLEM_NO_KEY,
        passport.ai_extractor.PROBLEM_NO_CREDIT,
        passport.ai_extractor.PROBLEM_API_ERROR,
    ]
    for code in codes:
        assert passport.CONTRACT_PROBLEM_MESSAGES[code].strip()


# --- VAT rate follows the signing year, not the document ---

def test_vat_for_year_is_20_percent_through_2025():
    assert passport.vat_for_year(2024) == "20%"
    assert passport.vat_for_year(2025) == "20%"


def test_vat_for_year_is_22_percent_from_2026():
    assert passport.vat_for_year(2026) == "22%"
    assert passport.vat_for_year(2030) == "22%"


def test_vat_for_year_accepts_the_year_as_stored_string():
    assert passport.vat_for_year("2025") == "20%"
    assert passport.vat_for_year("2026") == "22%"


def test_vat_for_year_unknown_year_gives_no_rate():
    assert passport.vat_for_year(None) is None
    assert passport.vat_for_year("") is None
    assert passport.vat_for_year("не указан") is None


def test_build_contract_terms_sets_vat_from_signing_year(monkeypatch):
    _stub_pdf(monkeypatch, _PROTOCOL_TEXT)

    data, filled, _problem = passport.build_contract_terms("ignored.pdf", year_signed="2026")

    assert data["vat"] == "22%"
    assert "vat" in filled


def test_build_contract_terms_rule_wins_over_vat_read_from_document(monkeypatch):
    # The rate is statutory, so a figure recognized off a scan must not
    # override the rule for a known signing year.
    _stub_pdf(monkeypatch, "", images=[b"png"])
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({"vat": "18%"}, None),
    )

    data, _filled, _problem = passport.build_contract_terms("ignored.pdf", year_signed=2025)

    assert data["vat"] == "20%"


def test_build_contract_terms_keeps_document_vat_when_year_unknown(monkeypatch):
    _stub_pdf(monkeypatch, "", images=[b"png"])
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({"vat": "20%"}, None),
    )

    data, _filled, _problem = passport.build_contract_terms("ignored.pdf", year_signed=None)

    assert data["vat"] == "20%"


def test_build_contract_terms_without_year_or_document_vat_leaves_it_empty(monkeypatch):
    _stub_pdf(monkeypatch, _PROTOCOL_TEXT)

    data, _filled, _problem = passport.build_contract_terms("ignored.pdf")

    assert data["vat"] is None


def test_build_contract_terms_still_warns_when_only_the_vat_rule_filled_anything(monkeypatch):
    # The rule always yields a rate for a known year, so it must not mask
    # the fact that the document itself gave nothing.
    _stub_pdf(monkeypatch, "", images=[b"png"])
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images: ({}, None),
    )

    data, filled, problem = passport.build_contract_terms("ignored.pdf", year_signed="2026")

    assert data["vat"] == "22%"
    assert filled == ["vat"]
    assert problem == passport.CONTRACT_PROBLEM_NOTHING_FOUND
