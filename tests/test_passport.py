from app import ocr, passport
from tests.helpers import document_xml, make_docx


def test_passport_fields_order():
    assert passport.PASSPORT_FIELDS == [
        "project_name", "year_signed", "building_class",
        "general_contractor", "underground_area_sqm",
        "aboveground_area_sqm", "total_area_sqm",
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
    data = {
        "project_name": "Проспект Мира",
        "year_signed": None,
        "building_class": None,
        "general_contractor": "ООО «АНТТЕК»",
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": None,
    }
    path = tmp_path / "passport.json"
    passport.save_passport(data, path)
    loaded = passport.load_passport(path)
    assert loaded == data


def test_save_passport_writes_readable_utf8(tmp_path):
    data = {"project_name": "Проспект Мира"}
    path = tmp_path / "passport.json"
    passport.save_passport(data, path)
    text = path.read_text(encoding="utf-8")
    assert "Проспект Мира" in text


def test_build_passport_ocr_fallback_fills_area_from_image(tmp_path, monkeypatch):
    # OCR сам по себе не тестируется здесь (см. tests/test_ocr.py и ручную
    # проверку на реальном файле) — только то, что passport.py правильно
    # применяет резерв и помечает поле как заполненное через OCR.
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
