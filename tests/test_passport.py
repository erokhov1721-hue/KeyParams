from app import passport
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
