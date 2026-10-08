from app.ocr_lines import Word, group_into_lines, normalize_text, normalize_words


def _line(*texts, y=100):
    return [Word(y=y, x0=i * 100, x1=i * 100 + 80, height=20, text=t) for i, t in enumerate(texts)]


# --- normalize_text ---

def test_percent_read_as_zero_slash_zero_is_a_percent_sign():
    assert normalize_text("0/0") == "%"
    assert normalize_text("300/0") == "30%"


def test_a_word_mixing_latin_and_cyrillic_is_made_cyrillic():
    assert normalize_text("He") == "He"  # целиком латиница — без строки не решить
    assert normalize_text("Heт") == "Нет"
    assert normalize_text("включeно") == "включено"


def test_a_lookalike_only_word_is_made_cyrillic_on_a_cyrillic_line():
    assert normalize_text("CMP", line_is_cyrillic=True) == "СМР"
    assert normalize_text("He", line_is_cyrillic=True) == "Не"


def test_a_lookalike_only_word_stays_latin_on_a_latin_line():
    assert normalize_text("CMP", line_is_cyrillic=False) == "CMP"


def test_genuinely_latin_words_are_never_touched():
    for word in ("bond", "performance", "Performance", "MR", "Base", "BIM"):
        assert normalize_text(word, line_is_cyrillic=True) == word


def test_digits_and_punctuation_are_left_alone():
    assert normalize_text("33", line_is_cyrillic=True) == "33"
    assert normalize_text("2,5%", line_is_cyrillic=True) == "2,5%"


# --- normalize_words ---

def test_normalize_words_judges_each_word_by_its_own_line():
    words = _line("Срок", "выполнения", "CMP", "33", "месяца", y=100) + _line(
        "Performance", "bond", "5%", y=200,
    )

    texts = [w.text for w in normalize_words(words)]

    assert texts == ["Срок", "выполнения", "СМР", "33", "месяца", "Performance", "bond", "5%"]


def test_normalize_words_keeps_bond_on_a_mostly_cyrillic_line():
    words = _line("5", "Performance", "bond,", "%", "(Банковская", "гарантия", "на", "исполнение")

    texts = [w.text for w in normalize_words(words)]

    assert texts[1:3] == ["Performance", "bond,"]


def test_normalize_words_keeps_order_and_positions():
    words = _line("Аванс,", "0/0", "300/0")

    result = normalize_words(words)

    assert [w.text for w in result] == ["Аванс,", "%", "30%"]
    assert [(w.x0, w.y) for w in result] == [(w.x0, w.y) for w in words]


def test_group_into_lines_is_unchanged_by_the_refactor():
    words = _line("б", "а", y=100)[::-1] + _line("в", y=200)
    # Слова поданы задом наперёд — в строке они встают по горизонтали.
    assert group_into_lines(words) == ["б а", "в"]
