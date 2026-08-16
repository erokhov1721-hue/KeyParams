from app import win_ocr
from app.ocr_lines import Word, group_into_lines


def _png():
    """Байты крошечной картинки — движок в этих тестах подменён."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="PNG")
    return buf.getvalue()


def _word(text, x, y, width=40, height=20):
    return {"text": text, "bounding_rect": {"x": x, "y": y, "width": width, "height": height}}


def _result(lines):
    return {"lines": [{"words": words} for words in lines]}


# --- group_into_lines ---

def test_group_into_lines_joins_fragments_on_the_same_row():
    lines = group_into_lines([
        Word(y=10, x0=300, x1=360, height=20, text="67 413"),
        Word(y=10, x0=100, x1=260, height=20, text="Общая площадь"),
        Word(y=60, x0=100, x1=160, height=20, text="Класс"),
    ])

    assert lines == ["Общая площадь 67 413", "Класс"]


def test_group_into_lines_orders_rows_top_to_bottom():
    lines = group_into_lines([
        Word(y=100, x0=10, x1=70, height=20, text="третья"),
        Word(y=10, x0=10, x1=70, height=20, text="первая"),
        Word(y=55, x0=10, x1=70, height=20, text="вторая"),
    ])

    assert lines == ["первая", "вторая", "третья"]


def test_group_into_lines_tolerates_a_small_vertical_wobble():
    # Two fragments of one row rarely sit at exactly the same height.
    lines = group_into_lines([
        Word(y=100, x0=10, x1=70, height=20, text="Аванс"),
        Word(y=104, x0=200, x1=240, height=20, text="30%"),
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

def test_recognize_text_is_empty_when_the_engine_reads_nothing(monkeypatch):
    def boom(data):
        return []

    monkeypatch.setattr(win_ocr, "recognize_page_words", boom)

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


# --- страница читается любой стороной вверх ---

def test_a_page_that_reads_upright_is_not_turned(monkeypatch):
    from PIL import Image

    tried = []

    def recognise(image, angle):
        tried.append(angle)
        return [Word(y=0, x0=0, x1=10, height=20, text="я" * win_ocr.READS_PROPERLY)]

    monkeypatch.setattr(win_ocr, "_recognize_at", recognise)

    words = win_ocr.recognize_page_words(_png())

    assert tried == [0], "лишние попытки стоят по секунде каждая"
    assert words


def test_a_sideways_page_is_turned_until_it_reads(monkeypatch):
    # The rotation recorded in a PDF is no guide: of two protocols from one
    # office, the upright one carried /Rotate 180 and the sideways one 270.
    tried = []

    def recognise(image, angle):
        tried.append(angle)
        if angle != 270:
            return [Word(y=0, x0=0, x1=10, height=20, text="аб")]
        return [Word(y=0, x0=0, x1=10, height=20, text="я" * win_ocr.READS_PROPERLY)]

    monkeypatch.setattr(win_ocr, "_recognize_at", recognise)

    words = win_ocr.recognize_page_words(_png())

    assert tried == [0, 90, 180, 270]
    assert len(words[0].text) >= win_ocr.READS_PROPERLY


def test_an_unreadable_page_gives_back_the_best_of_a_bad_lot(monkeypatch):
    def recognise(image, angle):
        count = 3 if angle == 180 else 1
        return [Word(y=0, x0=0, x1=10, height=20, text="a")] * count

    monkeypatch.setattr(win_ocr, "_recognize_at", recognise)

    assert len(win_ocr.recognize_page_words(_png())) == 3
