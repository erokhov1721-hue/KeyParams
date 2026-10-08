"""Настоящие протоколы против эталонов — по полю на тест.

Протоколы и эталоны лежат в tests/fixtures/protocols/ и в репозиторий не
попадают; без этой папки тесты пропускаются. Движок, которого на машине нет,
тоже пропускается.

Известные ошибки помечены strict xfail: если ошибка исчезнет, тест упадёт —
пометку тогда надо снять, а не оставить висеть.
"""

import functools
import json
from pathlib import Path

import pytest

from app import contract_extractors, passport, pdf_reader, tess_ocr, win_ocr

PROTOCOLS = Path(__file__).parent / "fixtures" / "protocols"
FIELDS = ("smr_term", "advance_payment", "bank_guarantee", "performance_bond_pct")

# (движок, протокол, объект, поле) -> почему ошибается.
KNOWN_FAILURES = {
    # Ошибки распознавания самих движков. Их закрывает каскад (см. записи
    # «cascade» — их тут нет): перечитывание ячейки, следующий способ.
    ("tesseract", "veer_ub9", "Верейская UB2", "advance_payment"):
        "Tesseract читает «30%,» колонки UB2 как «0%,» — неверное значение",
    ("windows", "veer_ub9", "Верейская UB9", "advance_payment"):
        "пропуск: Windows OCR не ставит «30%,» ни в строку подписи, ни строкой выше",
    ("windows", "veer_ub9", "Верейская UB2", "advance_payment"):
        "пропуск: Windows OCR читает «30%,» этой колонки как «зоољ.»",
    ("windows", "veer_ub9", "Верейская UB2", "performance_bond_pct"):
        "пропуск: Windows OCR теряет «3%» в строке bond колонки UB2",
    ("windows", "city_bay_3", "CITY BAY 3", "advance_payment"):
        "пропуск: Windows OCR не читает строку аванса этого скана",
    ("windows", "city_bay_3", "CITY BAY 3", "performance_bond_pct"):
        "пропуск: Windows OCR не читает строку performance bond этого скана",
}


def _golden():
    if not PROTOCOLS.is_dir():
        return []
    return [
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(PROTOCOLS.glob("*.json"))
    ]


def _cases():
    cases = []
    for engine in ("tesseract", "windows", "cascade"):
        for key, gold in _golden():
            for obj in gold["objects"]:
                for field in FIELDS:
                    marks = []
                    reason = KNOWN_FAILURES.get((engine, key, obj["name"], field))
                    if reason:
                        marks.append(pytest.mark.xfail(reason=reason, strict=True))
                    cases.append(pytest.param(
                        engine, key, obj["name"], field,
                        id=f"{engine}-{key}-{obj['name']}-{field}", marks=marks,
                    ))
    return cases


@pytest.fixture(autouse=True)
def tesseract_off():
    """Здесь нужен настоящий Tesseract: заменяет одноимённую фикстуру из
    conftest.py, которая выключает его во всех остальных тестах."""
    yield


@pytest.fixture(autouse=True)
def windows_ocr_off():
    """Здесь нужен настоящий Windows OCR, а не выключенный, как в остальных
    тестах (см. conftest.py): эта фикстура заменяет ту одноимённую."""
    yield


ENGINES = {
    "tesseract": (tess_ocr, tess_ocr.RENDER_DPI),
    "windows": (win_ocr, 200),
}


def _available(engine):
    if engine == "tesseract":
        tess_ocr.reset_availability()
        return tess_ocr.available()
    return win_ocr.available()


@functools.lru_cache(maxsize=None)
def _pages(engine, key):
    """Распознанные страницы протокола — один раз на движок и протокол."""
    module, dpi = ENGINES[engine]
    gold = dict(_golden())[key]
    images = pdf_reader.render_pages_to_images(
        PROTOCOLS / gold["file"], resolution=dpi, max_long_edge=None,
    )
    return tuple(tuple(module.recognize_page_words(image)) for image in images)


@functools.lru_cache(maxsize=None)
def _found(engine, key, project_name):
    pages = [list(page) for page in _pages(engine, key)]
    text, _ambiguous = passport._protocol_text(pages, project_name)
    found = passport._terms_from_text(text)
    found["smr_term"] = contract_extractors.bare_number(found["smr_term"])
    found["advance_payment"] = contract_extractors.percent_value(found["advance_payment"])
    return found


# Итог каскада без платного Claude: Tesseract, затем Windows OCR для того,
# чего Tesseract не нашёл.
CASCADE_ORDER = "tesseract,windows"


@functools.lru_cache(maxsize=None)
def _cascade(key, project_name, year_signed):
    import os
    gold = dict(_golden())[key]
    previous = os.environ.get(passport.SCAN_ORDER_ENV)
    os.environ[passport.SCAN_ORDER_ENV] = CASCADE_ORDER
    try:
        data, _filled, _problem = passport.build_contract_terms(
            PROTOCOLS / gold["file"], year_signed=year_signed, project_name=project_name,
        )
    finally:
        if previous is None:
            os.environ.pop(passport.SCAN_ORDER_ENV, None)
        else:
            os.environ[passport.SCAN_ORDER_ENV] = previous
    return data


def _norm(value):
    return None if value is None else str(value).replace(" ", "").lower().replace(",", ".")


@pytest.mark.parametrize("engine,key,name,field", _cases())
def test_field_matches_the_golden_value(engine, key, name, field, monkeypatch):
    for variable in (tess_ocr.PSM_ENV, tess_ocr.TESSDATA_ENV, tess_ocr.CMD_ENV,
                     tess_ocr.DESKEW_ENV, tess_ocr.BINARIZE_ENV, tess_ocr.REMOVE_LINES_ENV):
        monkeypatch.delenv(variable, raising=False)
    if engine == "cascade":
        if not _available("tesseract"):
            pytest.skip("Tesseract недоступен на этой машине")
    elif not _available(engine):
        pytest.skip(f"движок {engine} недоступен на этой машине")
    gold = dict(_golden())[key]
    obj = next(o for o in gold["objects"] if o["name"] == name)

    if engine == "cascade":
        found = _cascade(key, obj["project_name"], obj["year_signed"])
    else:
        found = _found(engine, key, obj["project_name"])

    assert _norm(found[field]) == _norm(obj["fields"][field]["expected"])


def test_golden_files_are_present_or_the_suite_says_so():
    if not _golden():
        pytest.skip("нет папки tests/fixtures/protocols с настоящими протоколами")
