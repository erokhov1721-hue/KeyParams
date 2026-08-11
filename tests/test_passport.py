from app import ocr, passport
from tests.helpers import document_xml, make_docx


def test_passport_fields_order():
    assert passport.PASSPORT_FIELDS == [
        "project_name", "year_signed", "building_class",
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

def _passport(name, price=None, year=None, building_class=None, area=None):
    return {
        "project_name": name, "year_signed": year, "building_class": building_class,
        "general_contractor": None, "contract_price_rub": price,
        "underground_area_sqm": None, "aboveground_area_sqm": None,
        "total_area_sqm": area, "ocr_fields": [],
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
    assert rows["Проект А"]["display"] == "100.00"


def test_charts_price_per_sqm_skips_when_not_computable():
    passports = {
        "a": _passport("Проект А", price=300.0, area=None),
        "b": _passport("Проект Б", price=100.0, area=1.0),
    }
    charts = passport.build_comparison_charts(passports, ["a", "b"])
    assert [row["label"] for row in charts["price_per_sqm"]] == ["Проект Б"]


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
    data = {
        "project_name": "Проспект Мира",
        "year_signed": None,
        "building_class": None,
        "general_contractor": "ООО «АНТТЕК»",
        "contract_price_rub": None,
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": None,
    }
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


def test_build_passport_ocr_disabled_by_default(tmp_path, monkeypatch):
    # OCR is opt-in (OCR_FALLBACK_ENABLED=1) because EasyOCR is CPU-only and
    # slow in this environment. With the env var unset, recognize_text must
    # never be called, even when fields are missing and images are present.
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
