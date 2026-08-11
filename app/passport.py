import json
from pathlib import Path

from . import extractors, ocr
from .document_reader import DocxContent, read_docx

PASSPORT_FIELDS = [
    "project_name", "year_signed", "building_class",
    "general_contractor", "underground_area_sqm",
    "aboveground_area_sqm", "total_area_sqm",
]

FIELD_LABELS = {
    "project_name": "Название проекта",
    "year_signed": "Год подписания договора",
    "building_class": "Класс здания",
    "general_contractor": "Генподрядчик",
    "underground_area_sqm": "Площадь подземной части, м²",
    "aboveground_area_sqm": "Площадь надземной части, м²",
    "total_area_sqm": "Общая площадь комплекса, м²",
}

TEXT_FIELDS = ("year_signed", "building_class", "general_contractor")
AREA_FIELDS = ("underground_area_sqm", "aboveground_area_sqm", "total_area_sqm")

AREA_TOKENS = {
    "underground_area_sqm": (('площад', 'подземн'), extractors.FOOTPRINT_EXCLUSION),
    "aboveground_area_sqm": (
        ('площад', ('надземн', 'наземн')), extractors.FOOTPRINT_EXCLUSION,
    ),
    "total_area_sqm": (
        ('обща', 'площад'),
        ('подземн', 'надземн', 'наземн') + extractors.FOOTPRINT_EXCLUSION,
    ),
}


def _ocr_lines(images):
    if not images:
        return []
    lines = []
    for text in ocr.recognize_text(images):
        lines.extend(text.splitlines())
    return lines


def _apply_ocr_fallback(data, dgp, tz):
    missing = [f for f in PASSPORT_FIELDS if f != "project_name" and data[f] is None]
    if not missing:
        return []

    needs_dgp_ocr = any(f in TEXT_FIELDS for f in missing)
    needs_tz_ocr = any(f == "building_class" or f in AREA_FIELDS for f in missing)

    dgp_lines = _ocr_lines(dgp.images) if needs_dgp_ocr else []
    tz_lines = _ocr_lines(tz.images) if needs_tz_ocr else []

    ocr_dgp = DocxContent(paragraphs=dgp_lines, tables=[])
    ocr_tz = DocxContent(paragraphs=tz_lines, tables=[])

    filled = []
    if data["general_contractor"] is None:
        value = extractors.extract_general_contractor(ocr_dgp)
        if value is not None:
            data["general_contractor"] = value
            filled.append("general_contractor")
    if data["year_signed"] is None:
        value = extractors.extract_signing_year(ocr_dgp)
        if value is not None:
            data["year_signed"] = value
            filled.append("year_signed")
    if data["building_class"] is None:
        value = extractors.extract_building_class(ocr_dgp, ocr_tz)
        if value is not None:
            data["building_class"] = value
            filled.append("building_class")
    for field in AREA_FIELDS:
        if data[field] is not None:
            continue
        must_contain, must_not_contain = AREA_TOKENS[field]
        value = extractors._find_area_value_in_text(tz_lines, must_contain, must_not_contain)
        if value is not None:
            data[field] = value
            filled.append(field)
    return filled


def build_passport(project_name: str, dgp_path, tz_path) -> dict:
    dgp = read_docx(dgp_path)
    tz = read_docx(tz_path)
    data = {
        "project_name": project_name,
        "year_signed": extractors.extract_signing_year(dgp),
        "building_class": extractors.extract_building_class(dgp, tz),
        "general_contractor": extractors.extract_general_contractor(dgp),
        "underground_area_sqm": extractors.extract_underground_area(tz),
        "aboveground_area_sqm": extractors.extract_aboveground_area(tz),
        "total_area_sqm": extractors.extract_total_area(tz),
    }
    data["ocr_fields"] = _apply_ocr_fallback(data, dgp, tz)
    return data


def save_passport(passport_data: dict, path: Path) -> None:
    path.write_text(
        json.dumps(passport_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_passport(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
