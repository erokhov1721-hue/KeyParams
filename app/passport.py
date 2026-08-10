import json
from pathlib import Path

from . import extractors
from .document_reader import read_docx

PASSPORT_FIELDS = [
    "project_name", "year_signed", "building_class",
    "general_contractor", "underground_area_sqm",
    "aboveground_area_sqm", "total_area_sqm",
]


def build_passport(project_name: str, dgp_path, tz_path) -> dict:
    dgp = read_docx(dgp_path)
    tz = read_docx(tz_path)
    return {
        "project_name": project_name,
        "year_signed": extractors.extract_signing_year(dgp),
        "building_class": extractors.extract_building_class(dgp, tz),
        "general_contractor": extractors.extract_general_contractor(dgp),
        "underground_area_sqm": extractors.extract_underground_area(tz),
        "aboveground_area_sqm": extractors.extract_aboveground_area(tz),
        "total_area_sqm": extractors.extract_total_area(tz),
    }


def save_passport(passport_data: dict, path: Path) -> None:
    path.write_text(
        json.dumps(passport_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_passport(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
