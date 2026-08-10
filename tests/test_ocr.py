import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from app import ocr


def _text_image(text):
    img = Image.new("RGB", (700, 150), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=48)
    draw.text((10, 30), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _easyocr_available():
    try:
        ocr._get_reader()
        return True
    except Exception:
        return False


def test_recognize_text_reads_clear_text():
    if not _easyocr_available():
        pytest.skip("EasyOCR не смог инициализироваться в этой среде (нет сети для загрузки модели?)")
    result = ocr.recognize_text([_text_image("HELLO 12345")])
    assert len(result) == 1
    assert "12345" in result[0]


def test_recognize_text_ignores_unreadable_image():
    result = ocr.recognize_text([b"not an image at all"])
    assert result == [""]


def test_recognize_text_empty_list():
    assert ocr.recognize_text([]) == []


def test_recognize_text_preserves_order_and_count():
    result = ocr.recognize_text([b"bad-1", b"bad-2", b"bad-3"])
    assert result == ["", "", ""]


def test_group_into_lines_groups_by_vertical_position():
    # Two phrases roughly on the same visual line (y around 0-20), one
    # phrase well below (y around 100-120) — mirrors how EasyOCR splits
    # "Общая площадь" and "67 413" into separate detections.
    detections = [
        ([[0, 0], [50, 0], [50, 20], [0, 20]], "Общая", 0.9),
        ([[60, 2], [140, 2], [140, 22], [60, 22]], "площадь", 0.9),
        ([[0, 100], [80, 100], [80, 120], [0, 120]], "67 413", 0.9),
    ]
    assert ocr._group_into_lines(detections) == ["Общая площадь", "67 413"]


def test_group_into_lines_empty_input():
    assert ocr._group_into_lines([]) == []
