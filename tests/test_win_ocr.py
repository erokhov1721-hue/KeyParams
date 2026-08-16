from app import win_ocr
from app.ocr_lines import group_into_lines


def _word(text, x, y, width=40, height=20):
    return {"text": text, "bounding_rect": {"x": x, "y": y, "width": width, "height": height}}


def _result(lines):
    return {"lines": [{"words": words} for words in lines]}


# --- group_into_lines ---

def test_group_into_lines_joins_fragments_on_the_same_row():
    lines = group_into_lines([
        (10, 300, 20, "67 413"),
        (10, 100, 20, "Общая площадь"),
        (60, 100, 20, "Класс"),
    ])

    assert lines == ["Общая площадь 67 413", "Класс"]


def test_group_into_lines_orders_rows_top_to_bottom():
    lines = group_into_lines([
        (100, 10, 20, "третья"),
        (10, 10, 20, "первая"),
        (55, 10, 20, "вторая"),
    ])

    assert lines == ["первая", "вторая", "третья"]


def test_group_into_lines_tolerates_a_small_vertical_wobble():
    # Two fragments of one row rarely sit at exactly the same height.
    lines = group_into_lines([
        (100, 10, 20, "Аванс"),
        (104, 200, 20, "30%"),
    ])

    assert lines == ["Аванс 30%"]


def test_group_into_lines_of_nothing_is_nothing():
    assert group_into_lines([]) == []


# --- _text_from_result ---

def test_reading_order_is_rebuilt_across_columns():
    # Windows reads a table column by column: every number first, then every
    # label. Laid out by position, the row goes back together.
    result = _result([
        [_word("1", 100, 500), _word("2", 100, 560)],
        [_word("Аванс", 300, 500), _word("Срок", 300, 560)],
        [_word("30%", 800, 500), _word("30 месяцев", 800, 560)],
    ])

    assert win_ocr._text_from_result(result) == "1 Аванс 30%\n2 Срок 30 месяцев"


def test_percent_sign_misread_as_zero_slash_zero_is_repaired():
    result = _result([[
        _word("Аванс,", 100, 100), _word("0/0", 200, 100),
        _word("300/0", 300, 100), _word("200/0", 400, 100),
    ]])

    assert win_ocr._text_from_result(result) == "Аванс, % 30% 20%"


def test_text_from_an_empty_result_is_empty():
    assert win_ocr._text_from_result({"lines": []}) == ""
    assert win_ocr._text_from_result({}) == ""


# --- recognize_text never raises ---

def test_recognize_text_returns_empty_text_when_the_engine_fails(monkeypatch):
    def boom(data):
        raise RuntimeError("движок недоступен")

    monkeypatch.setattr(win_ocr, "_recognize_one", boom)

    assert win_ocr.recognize_text([b"png", b"png"]) == ["", ""]


def test_recognize_text_of_no_images_is_no_texts():
    assert win_ocr.recognize_text([]) == []


def test_available_is_false_when_the_package_is_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_winocr(name, *args, **kwargs):
        if name == "winocr":
            raise ImportError("нет пакета winocr")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_winocr)

    assert win_ocr.available() is False
