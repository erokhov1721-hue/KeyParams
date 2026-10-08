from pathlib import Path

import pytest

from app import tess_ocr, win_ocr
from app.document_reader import read_docx

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DGP_FIXTURE = FIXTURES_DIR / "dgp_mira.docx"
TZ_FIXTURE = FIXTURES_DIR / "tz_mira.docx"


@pytest.fixture(autouse=True)
def windows_ocr_off(monkeypatch):
    """Switch off the Windows OCR engine for every test by default.

    Whether the machine running the tests happens to have that engine — and
    the Russian language pack it needs — must not change what the tests say.
    A test that wants it turns it back on itself.
    """
    monkeypatch.setattr(win_ocr, "available", lambda: False)


@pytest.fixture(autouse=True)
def tesseract_off(monkeypatch):
    """Switch Tesseract off for every test by default, for the same reason:
    whether this machine has it must not change what the tests say. Tests of
    the engine itself (test_tess_ocr.py, test_real_protocols.py) replace this
    fixture with one that leaves it alone."""
    monkeypatch.setattr(
        tess_ocr, "availability", lambda: (False, "выключен в тестах"),
    )
    monkeypatch.setattr(tess_ocr, "available", lambda: False)


def _require_fixture(path):
    if not path.exists():
        pytest.skip(
            f"Реальный файл-пример не найден: {path}. "
            "Скопируйте его туда перед запуском этого теста (см. план)."
        )


@pytest.fixture(scope="session")
def real_dgp():
    _require_fixture(DGP_FIXTURE)
    return read_docx(DGP_FIXTURE)


@pytest.fixture(scope="session")
def real_tz():
    _require_fixture(TZ_FIXTURE)
    return read_docx(TZ_FIXTURE)
