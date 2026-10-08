import io
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app import ocr_lines, tess_ocr

FONT = Path(r"C:\Windows\Fonts\arial.ttf")


@pytest.fixture(autouse=True)
def fresh_availability(monkeypatch):
    for name in (
        tess_ocr.CMD_ENV, tess_ocr.TESSDATA_ENV, tess_ocr.PSM_ENV, tess_ocr.TIMEOUT_ENV,
        tess_ocr.DESKEW_ENV, tess_ocr.BINARIZE_ENV, tess_ocr.REMOVE_LINES_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    tess_ocr.reset_availability()
    yield
    tess_ocr.reset_availability()


def _needs_tesseract():
    tess_ocr.reset_availability()
    if not tess_ocr.available():
        pytest.skip(f"Tesseract недоступен: {tess_ocr.availability()[1]}")


# --- разбор вывода программы ---

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t1400\t260\t-1\t\n"
    "4\t1\t1\t1\t1\t0\t32\t38\t289\t35\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t32\t38\t18\t30\t94.8\t3\n"
    "5\t1\t1\t1\t1\t2\t63\t38\t120\t36\t93.2\tАванс,\n"
    "5\t1\t1\t1\t1\t3\t199\t38\t31\t30\t93.2\t \n"
)


def test_parse_tsv_takes_words_with_their_positions():
    words = tess_ocr.parse_tsv(TSV)

    assert [w.text for w in words] == ["3", "Аванс,"]
    assert words[1] == ocr_lines.Word(y=56.0, x0=63.0, x1=183.0, height=36.0, text="Аванс,")


def test_parse_tsv_of_nothing_is_no_words():
    assert tess_ocr.parse_tsv("") == []
    assert tess_ocr.parse_tsv("не TSV вовсе") == []


def test_parse_osd_reads_rotation_and_confidence():
    report = (
        "Page number: 0\nOrientation in degrees: 270\nRotate: 90\n"
        "Orientation confidence: 2.68\nScript: Cyrillic\nScript confidence: 6.67\n"
    )
    assert tess_ocr.parse_osd(report) == (90, 2.68)
    assert tess_ocr.parse_osd("Too few characters. Skipping this page") is None


# --- запуск программы ---

class _Completed:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


def test_run_passes_a_list_without_shell_and_decodes_utf8(monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return _Completed("Аванс".encode("utf-8"))

    monkeypatch.setattr(tess_ocr.subprocess, "run", fake_run)

    out = tess_ocr._run(["tesseract", "--version"], b"png")

    assert out == "Аванс"
    assert isinstance(seen["args"], list)
    assert "shell" not in seen["kwargs"]
    assert seen["kwargs"]["input"] == b"png"
    assert seen["kwargs"]["timeout"] == tess_ocr.DEFAULT_TIMEOUT
    if sys.platform == "win32":
        assert seen["kwargs"]["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_models_are_passed_as_tessdata_dir_not_through_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(tess_ocr.TESSDATA_ENV, str(tmp_path))
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"], seen["env"] = args, kwargs.get("env")
        return _Completed(TSV.encode("utf-8"))

    monkeypatch.setattr(tess_ocr.subprocess, "run", fake_run)

    tess_ocr._recognize(Image.new("L", (10, 10), 255))

    assert seen["args"][seen["args"].index("--tessdata-dir") + 1] == str(tmp_path)
    assert seen["env"] is None
    assert "tsv" in seen["args"]
    assert seen["args"][seen["args"].index("--psm") + 1] == str(tess_ocr.DEFAULT_PSM)


def test_a_missing_program_makes_the_engine_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv(tess_ocr.CMD_ENV, str(tmp_path / "нет-такой-программы.exe"))

    ok, reason = tess_ocr.availability()

    assert not ok
    assert "не найдена программа Tesseract" in reason
    assert tess_ocr.recognize_page_words(b"png") == []


def test_a_missing_russian_model_makes_the_engine_unavailable(monkeypatch, tmp_path):
    program = tmp_path / "tesseract.exe"
    program.write_bytes(b"")
    monkeypatch.setenv(tess_ocr.CMD_ENV, str(program))
    monkeypatch.setattr(
        tess_ocr.subprocess, "run",
        lambda args, **kw: _Completed(b"List of available languages (2):\neng\nosd\n"),
    )

    ok, reason = tess_ocr.availability()

    assert not ok
    assert "rus" in reason


def test_a_page_that_runs_out_of_time_reads_as_no_words(monkeypatch):
    monkeypatch.setattr(tess_ocr, "available", lambda: True)

    def too_slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("tesseract", 1)

    monkeypatch.setattr(tess_ocr, "_run", too_slow)
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")

    assert tess_ocr.recognize_page_words(buf.getvalue()) == []


# --- подготовка страницы ---

def _text_image(lines, size=(1400, 300)):
    if not FONT.exists():
        pytest.skip("нет шрифта Arial для тестовой картинки")
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 40)
    for i, line in enumerate(lines):
        draw.text((30, 30 + 80 * i), line, fill=0, font=font)
    return image


SAMPLE = ["3 Аванс, % 30%", "Срок выполнения СМР 33 месяца", "Performance bond 5%"]


@pytest.mark.parametrize("tilt", [0, 2, -2, 3])
def test_skew_angle_finds_how_far_the_page_is_tilted(tilt):
    import numpy as np

    page = _text_image(SAMPLE).rotate(tilt, expand=True, fillcolor=255)

    assert tess_ocr.skew_angle(np.array(page)) == pytest.approx(-tilt, abs=0.3)


def test_preprocess_switches_follow_the_settings(monkeypatch):
    import numpy as np

    page = _text_image(SAMPLE).convert("RGB")

    binary = np.unique(np.array(tess_ocr.preprocess(page)))
    assert set(binary.tolist()) <= {0, 255}

    monkeypatch.setenv(tess_ocr.BINARIZE_ENV, "0")
    grey = np.unique(np.array(tess_ocr.preprocess(page)))
    assert len(grey) > 2


# --- настоящий Tesseract ---

def _png(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("turn", [0, 90, 180, 270])
def test_tesseract_reads_a_page_whichever_way_up_it_is(turn):
    _needs_tesseract()
    page = _text_image(SAMPLE).rotate(turn, expand=True, fillcolor=255)

    lines = ocr_lines.group_into_lines(tess_ocr.recognize_page_words(_png(page)))

    assert lines == SAMPLE


def test_tesseract_output_goes_through_the_shared_normalization():
    _needs_tesseract()
    page = _text_image(["Банковская гарантия 0/0"])

    text = " ".join(w.text for w in tess_ocr.recognize_page_words(_png(page)))

    assert "0/0" not in text


# --- контрольные суммы моделей ---

def test_models_matching_the_reference_raise_no_warning(tmp_path, monkeypatch, caplog):
    model = tmp_path / "rus.traineddata"
    model.write_bytes(b"x")
    monkeypatch.setattr(tess_ocr, "MODEL_SHA256", {"rus.traineddata": tess_ocr._sha256(model)})

    with caplog.at_level("WARNING"):
        assert tess_ocr.check_models(tmp_path) == []
    assert "отличается" not in caplog.text


def test_a_different_model_is_warned_about(tmp_path, caplog):
    (tmp_path / "rus.traineddata").write_bytes(b"not the reference model")

    with caplog.at_level("WARNING"):
        differing = tess_ocr.check_models(tmp_path)

    assert differing == ["rus.traineddata"]
    assert "отличается от эталонной" in caplog.text


def test_the_installed_models_are_the_reference_ones():
    _needs_tesseract()
    folder, _languages = tess_ocr._languages()

    assert tess_ocr.check_models(folder) == []
