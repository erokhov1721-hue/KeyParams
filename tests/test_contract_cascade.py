"""Каскад методов распознавания протокола: порядок, добор только недостающих
полей, проверка значений, источники, нестандартная гарантия."""

import pytest

from app import passport, tess_ocr
from app.ocr_lines import Word
from tests.helpers import words_from_text

FULL = """1 Срок выполнения СМР, месяц 30 месяцев
3 Аванс, % 30%
4 Банковская гарантия на возврат аванса Не включено
5 Performance bond, % 3%
"""

# Без срока и без bond: их должен добрать следующий метод.
PARTIAL = """3 Аванс, % 30%
4 Банковская гарантия на возврат аванса Не включено
"""

# Достаточно текста, чтобы страница считалась прочитанной.
FILLER = "\n".join(f"{i} Посторонняя строка протокола без условий" for i in range(10, 22))


@pytest.fixture
def scan(monkeypatch):
    """Протокол-скан: текстового слоя нет, все методы подменены. Возвращает
    журнал вызовов и словарь, через который тест задаёт ответы методов."""
    calls = []
    answers = {
        "tesseract": FILLER,
        "windows": FILLER,
        "easyocr": FILLER,
        "claude": ({}, None),
    }
    monkeypatch.setattr(passport.pdf_reader, "read_pdf_text", lambda path: "")
    monkeypatch.setattr(
        passport.pdf_reader, "render_pages_to_images", lambda path, **kwargs: [b"png"],
    )
    monkeypatch.setattr(passport.tess_ocr, "availability", lambda: (True, None))
    monkeypatch.setattr(passport.tess_ocr, "available", lambda: True)
    monkeypatch.setattr(
        passport.tess_ocr, "recognize_page",
        lambda image: calls.append("tesseract") or (words_from_text(answers["tesseract"]), None),
    )
    monkeypatch.setattr(passport.win_ocr, "available", lambda: True)
    monkeypatch.setattr(
        passport.win_ocr, "recognize_page_words",
        lambda image: calls.append("windows") or words_from_text(answers["windows"]),
    )
    monkeypatch.setattr(
        passport.ocr, "recognize_page_words",
        lambda image: calls.append("easyocr") or words_from_text(answers["easyocr"]),
    )

    def claude(images, project_name=None):
        calls.append(("claude", project_name))
        return answers["claude"]

    monkeypatch.setattr(passport.ai_extractor, "extract_contract_terms_from_images", claude)
    monkeypatch.delenv(passport.SCAN_ORDER_ENV, raising=False)
    return calls, answers


def test_tesseract_goes_first_and_alone_when_it_finds_everything(scan):
    calls, answers = scan
    answers["tesseract"] = FULL + FILLER

    data, filled, problem = passport.build_contract_terms("x.pdf", project_name="Объект")

    assert calls == ["tesseract"]
    assert data["smr_term"] == "30"
    assert data["contract_sources"]["smr_term"] == passport.METHOD_TESSERACT
    assert problem is None


def test_later_methods_only_fill_what_is_missing_and_keep_what_was_found(scan):
    calls, answers = scan
    answers["tesseract"] = PARTIAL + FILLER
    # Claude отвечает и на найденное — его аванс не должен заменить 30%.
    answers["claude"] = ({"advance_payment": "15%", "smr_term": "33", "performance_bond_pct": "5%"}, None)

    data, _filled, problem = passport.build_contract_terms("x.pdf", project_name="Объект")

    assert data["advance_payment"] == "30%"
    assert data["smr_term"] == "33"
    assert data["performance_bond_pct"] == "5%"
    assert data["contract_sources"] == {
        "advance_payment": "tesseract", "bank_guarantee": "tesseract",
        "smr_term": "claude", "performance_bond_pct": "claude",
    }
    assert ("claude", "Объект") in calls
    assert "windows" not in calls, "всё уже найдено — дальше не идём"
    assert problem is None


def test_a_value_that_fails_the_check_counts_as_not_found(scan):
    calls, answers = scan
    answers["tesseract"] = FULL.replace("30 месяцев", "500 месяцев") + FILLER
    answers["claude"] = ({"smr_term": "33"}, None)

    data, _filled, _problem = passport.build_contract_terms("x.pdf")

    assert data["smr_term"] == "33"
    assert data["contract_sources"]["smr_term"] == "claude"


def test_a_zero_rate_counts_as_not_found(scan):
    _calls, answers = scan
    answers["tesseract"] = FULL.replace("Аванс, % 30%", "Аванс, % 0%") + FILLER
    answers["claude"] = ({"advance_payment": "30%"}, None)

    data, _filled, _problem = passport.build_contract_terms("x.pdf")

    assert data["advance_payment"] == "30%"


def test_the_order_comes_from_the_setting(scan, monkeypatch):
    calls, answers = scan
    answers["windows"] = FULL + FILLER
    monkeypatch.setenv(passport.SCAN_ORDER_ENV, "windows, tesseract, claude")

    data, _filled, _problem = passport.build_contract_terms("x.pdf")

    assert calls == ["windows"]
    assert data["contract_sources"]["smr_term"] == "windows"


def test_an_unknown_or_empty_order_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(passport.SCAN_ORDER_ENV, "что-то, непонятное")
    assert passport.contract_scan_order() == list(passport.DEFAULT_SCAN_ORDER)
    monkeypatch.setenv(passport.SCAN_ORDER_ENV, "")
    assert passport.contract_scan_order() == [
        "tesseract", "claude", "windows", "easyocr",
    ]


def test_a_missing_tesseract_is_explained_and_the_rest_carries_on(scan, monkeypatch):
    calls, answers = scan
    monkeypatch.setattr(
        passport.tess_ocr, "availability",
        lambda: (False, "не найдена программа Tesseract (tess_min/tesseract.exe)"),
    )
    answers["claude"] = ({"smr_term": "33", "advance_payment": "30%",
                          "bank_guarantee": "Не включено", "performance_bond_pct": "3%"}, None)

    data, _filled, problem = passport.build_contract_terms("x.pdf")

    assert "tesseract" not in calls
    assert data["contract_notes"] == [
        "Tesseract недоступен: не найдена программа Tesseract (tess_min/tesseract.exe).",
    ]
    assert data["smr_term"] == "33"
    assert problem is None


def test_easyocr_is_skipped_once_another_local_engine_read_the_page(scan):
    calls, answers = scan
    answers["tesseract"] = PARTIAL + FILLER
    answers["windows"] = FILLER

    passport.build_contract_terms("x.pdf")

    assert "easyocr" not in calls


def test_easyocr_still_runs_when_no_local_engine_read_the_page(scan):
    calls, answers = scan
    answers["tesseract"] = ""
    answers["windows"] = ""
    answers["easyocr"] = FULL + FILLER

    data, _filled, _problem = passport.build_contract_terms("x.pdf")

    assert "easyocr" in calls
    assert data["contract_sources"]["smr_term"] == "easyocr"


def test_a_read_page_with_no_conditions_reports_nothing_found(scan):
    _calls, answers = scan
    answers["claude"] = ({}, passport.ai_extractor.PROBLEM_NO_KEY)

    _data, filled, problem = passport.build_contract_terms("x.pdf")

    assert filled == []
    assert problem == passport.CONTRACT_PROBLEM_NOTHING_FOUND


def test_an_unusual_guarantee_is_kept_word_for_word_and_flagged(scan):
    _calls, answers = scan
    answers["tesseract"] = FULL.replace(
        "Не включено", "Все авансы на счёт ОБС",
    ) + FILLER

    data, _filled, _problem = passport.build_contract_terms("x.pdf")

    assert data["bank_guarantee"] == "Все авансы на счёт ОБС"
    assert data["contract_review"] == {"bank_guarantee": "Все авансы на счёт ОБС"}


@pytest.mark.parametrize("written,expected", [
    ("Не включено", "Не включено"), ("нет", "Не включено"),
    ("Включено", "Включено"), ("да", "Включено"),
])
def test_a_standard_guarantee_is_not_flagged(scan, written, expected):
    _calls, answers = scan
    answers["tesseract"] = FULL.replace("Не включено", written) + FILLER

    data, _filled, _problem = passport.build_contract_terms("x.pdf")

    assert data["bank_guarantee"] == expected
    assert data["contract_review"] == {}


def test_vat_from_claude_and_from_the_rule_say_where_they_came_from(scan):
    _calls, answers = scan
    answers["claude"] = ({"vat": "20%"}, None)

    data, _f, _p = passport.build_contract_terms("x.pdf")
    assert (data["vat"], data["contract_sources"]["vat"]) == ("20%", "claude")

    data, _f, _p = passport.build_contract_terms("x.pdf", year_signed=2026)
    assert (data["vat"], data["contract_sources"]["vat"]) == ("22%", "rule")


def test_the_text_layer_is_read_first_and_marked_as_such(monkeypatch):
    monkeypatch.setattr(passport.pdf_reader, "read_pdf_text", lambda path: FULL)

    data, _filled, problem = passport.build_contract_terms("x.pdf")

    assert set(data["contract_sources"].values()) == {"text"}
    assert data["contract_notes"] == []
    assert problem is None


# --- перечитывание ячеек ---

def test_a_cell_with_its_label_found_is_read_again_alone(monkeypatch):
    regions = []

    def read_region(page, box, whitelist=None):
        regions.append((box, whitelist))
        return "30%"

    monkeypatch.setattr(passport.tess_ocr, "read_region", read_region)
    words = [
        Word(y=100, x0=10, x1=60, height=20, text="3"),
        Word(y=100, x0=70, x1=160, height=20, text="Аванс,"),
        Word(y=100, x0=170, x1=190, height=20, text="%"),
        Word(y=200, x0=10, x1=900, height=20, text="конец"),
    ]

    found = passport._reread_cells([(words, object())], None, {})

    assert found["advance_payment"] == "30%"
    (box, whitelist), = [r for r in regions if r[1] == "0123456789%,."][:1]
    assert box[0] > 190 and box[2] == 900
    assert whitelist == "0123456789%,."


def test_a_field_already_found_is_not_read_again(monkeypatch):
    monkeypatch.setattr(
        passport.tess_ocr, "read_region",
        lambda *a, **k: pytest.fail("ячейка с найденным значением не перечитывается"),
    )
    words = [Word(y=100, x0=70, x1=160, height=20, text="Аванс,"),
             Word(y=100, x0=170, x1=190, height=20, text="%")]
    found = {"advance_payment": "30%", "smr_term": "30",
             "performance_bond_pct": "3%", "bank_guarantee": "Не включено"}

    assert passport._reread_cells([(words, object())], None, found) == {}


# --- страница объекта ---

def _project_with_contract(tmp_path, **extra):
    from app import storage
    slug = storage.create_project(tmp_path, "Объект")
    data = passport.build_passport("Объект")
    data.update({
        "smr_term": "33", "advance_payment": "20%",
        "bank_guarantee": "Все авансы на счёт ОБС", "performance_bond_pct": "2,5%", "vat": "20%",
        "contract_auto_fields": ["smr_term", "bank_guarantee"],
        "contract_sources": {"smr_term": "tesseract", "bank_guarantee": "claude"},
        "contract_review": {"bank_guarantee": "Все авансы на счёт ОБС"},
        "contract_notes": ["Tesseract недоступен: нет русской модели."],
    })
    data.update(extra)
    passport.save_passport(data, storage.passport_path(tmp_path, slug))
    return slug


def test_the_page_says_how_each_value_was_found_and_what_to_check(tmp_path):
    from app import create_app
    slug = _project_with_contract(tmp_path)

    body = create_app(tmp_path).test_client().get(f"/projects/{slug}").get_data(as_text=True)

    assert "Найдено в протоколе (Tesseract) — проверьте" in body
    assert "Найдено в протоколе (Claude) — проверьте" in body
    assert "нестандартное условие — проверьте" in body
    assert "В протоколе: «Все авансы на счёт ОБС»" in body
    assert "Tesseract недоступен: нет русской модели." in body


def test_editing_a_field_by_hand_clears_its_marks(tmp_path):
    from app import create_app, storage
    slug = _project_with_contract(tmp_path)
    client = create_app(tmp_path).test_client()
    data = passport.load_passport(storage.passport_path(tmp_path, slug))

    client.post(f"/projects/{slug}/contract", data={
        "version": data["version"],
        "smr_term": "33", "advance_payment": "20%",
        "bank_guarantee": "Не включено", "performance_bond_pct": "2,5%", "vat": "20%",
    })

    saved = passport.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["contract_review"] == {}
    assert saved["contract_sources"] == {"smr_term": "tesseract"}
