from app import protocol_columns
from app.ocr_lines import Word, group_into_lines

ROW_STEP = 60


def _row(index, *placed):
    """One row of a page: ``(x, text)`` pairs at the given row index."""
    return [
        Word(y=index * ROW_STEP, x0=x, x1=x + max(len(text), 1) * 12, height=20, text=text)
        for x, text in placed
    ]


def _two_object_protocol():
    """A protocol drawn up for two objects: labels on the left, a column of
    conditions each. Laid out like the real one — the words of a heading nearly
    touch, the columns stand well apart."""
    words = []
    # Заголовок над таблицей называет оба объекта сразу, и слова в нём идут
    # подряд — по нему выбирать колонку нельзя.
    words += _row(0, (380, "Протокол"), (500, "окончательных"), (700, "условий"),
                  (800, "по"), (840, "проектам"), (960, "Верейская"), (1080, "UB9"),
                  (1130, "и"), (1160, "UB2"))
    words += _row(1, (380, "п/п"), (600, "Наименование"),
                  (1080, "Верейская"), (1180, "UB9"),
                  (1520, "Верейская"), (1620, "UB2"))
    words += _row(2, (380, "1"), (420, "Срок"), (500, "выполнения"), (640, "СМР"),
                  (1000, "38"), (1060, "мес"),
                  (1440, "33"), (1500, "мес"))
    words += _row(3, (380, "2"), (420, "Аванс,"), (520, "%"),
                  (1000, "30%"),
                  (1440, "25%"))
    return words


def _single_object_protocol():
    words = []
    words += _row(1, (380, "п/п"), (600, "Наименование"), (1080, "Условия"))
    words += _row(2, (380, "1"), (420, "Срок"), (500, "выполнения"), (640, "СМР"),
                  (1000, "38"), (1060, "мес"))
    return words


def _text(words):
    return "\n".join(group_into_lines(words))


# --- поиск шапки ---

def test_the_header_row_is_found_and_the_project_column_identified():
    found = protocol_columns.find_project_column(_two_object_protocol(), "VEER UB9")

    assert found is not None
    columns, index = found
    assert [column.text for column in columns] == [
        "п/п", "Наименование", "Верейская UB9", "Верейская UB2",
    ]
    assert index == 2


def test_the_title_naming_every_object_is_not_mistaken_for_the_header():
    # Its words run together into one column, so it fails the test and the
    # real header underneath is found instead.
    _columns, index = protocol_columns.find_project_column(
        _two_object_protocol(), "VEER UB2",
    )

    assert index == 3


def test_a_name_matching_nothing_finds_no_column():
    assert protocol_columns.find_project_column(
        _two_object_protocol(), "Селигер парк",
    ) is None


def test_a_single_object_protocol_has_no_column_to_choose():
    assert protocol_columns.find_project_column(
        _single_object_protocol(), "VEER UB9",
    ) is None


# --- отбор колонки ---

def test_only_this_project_column_is_kept():
    kept, chosen = protocol_columns.keep_project_column(_two_object_protocol(), "VEER UB9")

    assert chosen is True
    text = _text(kept)
    assert "38 мес" in text
    assert "33 мес" not in text
    assert "30%" in text
    assert "25%" not in text


def test_the_labels_are_kept_alongside_the_chosen_column():
    kept, _chosen = protocol_columns.keep_project_column(_two_object_protocol(), "VEER UB9")

    text = _text(kept)
    assert "Срок выполнения СМР" in text
    assert "Аванс," in text


def test_the_second_object_column_can_be_chosen_too():
    # Choosing the right-hand column means dropping the one on its left, which
    # is told from the labels by its heading being named like ours.
    kept, chosen = protocol_columns.keep_project_column(_two_object_protocol(), "VEER UB2")

    assert chosen is True
    text = _text(kept)
    assert "33 мес" in text
    assert "38 мес" not in text
    assert "Срок выполнения СМР" in text


def test_a_single_object_protocol_is_left_untouched():
    words = _single_object_protocol()

    kept, chosen = protocol_columns.keep_project_column(words, "VEER UB9")

    assert chosen is False
    assert kept == words


def test_an_unmatched_name_leaves_the_page_untouched():
    words = _two_object_protocol()

    kept, chosen = protocol_columns.keep_project_column(words, "Селигер парк")

    assert chosen is False
    assert kept == words


def test_no_project_name_leaves_the_page_untouched():
    words = _two_object_protocol()

    kept, chosen = protocol_columns.keep_project_column(words, None)

    assert chosen is False
    assert kept == words


# --- признак «протокол на несколько объектов» ---

def test_a_two_object_protocol_is_recognised_as_such():
    assert protocol_columns.is_multi_object(_two_object_protocol()) is True


def test_a_single_object_protocol_is_not():
    assert protocol_columns.is_multi_object(_single_object_protocol()) is False


def test_an_empty_page_is_not():
    assert protocol_columns.is_multi_object([]) is False
