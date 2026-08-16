"""Picking one object's column out of a protocol that covers several.

A contract-terms protocol is sometimes drawn up for two objects at once: one
column of conditions per object, side by side under a header naming each.
Read as flat text the two columns merge, and the term of works comes out as
"38 месяцев ... 33 месяца" — two answers where one was wanted.

The columns are told apart by nothing but horizontal position, so this works
on positioned words: find the header row, cut it into columns, keep the one
whose heading matches the project's name, and drop the others.

A protocol covering a single object has no columns to choose between and is
left exactly as it was.
"""

import re
from collections import namedtuple

from .ocr_lines import LINE_TOLERANCE

Column = namedtuple("Column", "text x0 x1")

# A gap this wide, as a share of the page, separates one column of a header
# from the next. Inside a heading the words nearly touch — "Верейская" and
# "UB9" sat 7px apart on the page this was written against, where the columns
# themselves stood 300px clear of each other.
COLUMN_GAP_SHARE = 0.02

# Words shorter than this carry no identity: "и", "по", a stray digit. A name
# is matched on its distinctive parts — "UB9" is three characters and has to
# count.
MIN_TOKEN = 2

# Objects on one protocol are named alike ("Верейская UB9", "верейская UB2"),
# and that shared word is how a sibling column is told from a column of
# labels. It has to be a real word to mean anything: two label columns of an
# ordinary protocol shared "на" and "да", which was enough to have a
# single-object protocol reported as covering several.
MIN_NAME_TOKEN = 4

# A header row has to have at least this many columns to be worth reading as
# one: the labels, and two objects to choose between.
MIN_HEADER_COLUMNS = 3

_TOKEN_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)


def _tokens(text, minimum=MIN_TOKEN):
    return {t.lower() for t in _TOKEN_RE.findall(str(text or "")) if len(t) >= minimum}


def _name_tokens(text):
    return _tokens(text, MIN_NAME_TOKEN)


def _rows(words):
    ordered = sorted(words, key=lambda word: word.y)
    rows, current, current_y = [], [], None
    for word in ordered:
        if current and abs(word.y - current_y) > max(word.height, 1) * LINE_TOLERANCE:
            rows.append(current)
            current = []
        current.append(word)
        current_y = word.y
    if current:
        rows.append(current)
    return rows


def _columns(row, gap):
    """A row cut into columns wherever the words stand well apart."""
    ordered = sorted(row, key=lambda word: word.x0)
    columns, current = [], [ordered[0]]
    for word in ordered[1:]:
        if word.x0 - current[-1].x1 > gap:
            columns.append(current)
            current = []
        current.append(word)
    columns.append(current)
    return [
        Column(
            text=" ".join(w.text for w in group),
            x0=min(w.x0 for w in group),
            x1=max(w.x1 for w in group),
        )
        for group in columns
    ]


def _page_gap(words):
    left = min(word.x0 for word in words)
    right = max(word.x1 for word in words)
    return max((right - left) * COLUMN_GAP_SHARE, 1.0)


def find_project_column(words, project_name):
    """``(columns, index)`` of the header row naming ``project_name``, or None.

    The row has to name the project in exactly one of its columns. The title
    across the top of the page names every object at once — "по проектам
    Верейская UB9 и UB2" — but its words run together into a single column,
    so it fails the test and the real header is found underneath it.
    """
    wanted = _tokens(project_name)
    if not wanted or not words:
        return None

    gap = _page_gap(words)
    for row in _rows(words):
        columns = _columns(row, gap)
        if len(columns) < MIN_HEADER_COLUMNS:
            continue
        matches = [i for i, column in enumerate(columns) if _tokens(column.text) & wanted]
        if len(matches) == 1 and matches[0] > 0:
            return columns, matches[0]
    return None


def _other_object_columns(columns, index):
    """The columns belonging to the other objects, which have to go.

    Everything to the right of ours is another object's — a protocol puts its
    labels on the left and its objects after them. To the left there may be
    labels, which must stay, or an earlier object, which must not: those are
    told apart by their headings, since objects on one protocol are named
    alike ("Верейская UB9", "верейская UB2") while a label column shares
    nothing with them.
    """
    ours = _name_tokens(columns[index].text)
    doomed = list(range(index + 1, len(columns)))
    doomed += [
        i for i in range(index)
        if i > 0 and _name_tokens(columns[i].text) & ours
    ]
    return doomed


def keep_project_column(words, project_name):
    """``(words, chosen)`` — the page with only this project's column left.

    ``chosen`` is False when there was nothing to choose: either the protocol
    covers one object, or its columns are headed in a way that doesn't match
    the project's name. The words then come back untouched, and the caller
    can say so rather than quietly reading somebody else's figures.
    """
    found = find_project_column(words, project_name)
    if found is None:
        return words, False

    columns, index = found
    doomed = _other_object_columns(columns, index)
    if not doomed:
        return words, False

    def keeps(word):
        centre = (word.x0 + word.x1) / 2
        return not any(_within_column(centre, columns, i) for i in doomed)

    return [word for word in words if keeps(word)], True


def _within_column(centre, columns, index):
    """Whether a word sits under the given header, the boundary with its
    neighbours being halfway to each of them."""
    left = columns[index - 1].x1 if index > 0 else float("-inf")
    right = columns[index + 1].x0 if index + 1 < len(columns) else float("inf")
    lower = (left + columns[index].x0) / 2 if left != float("-inf") else float("-inf")
    upper = (columns[index].x1 + right) / 2 if right != float("inf") else float("inf")
    return lower <= centre <= upper


def is_multi_object(words, project_name=None):
    """Whether the page looks like a protocol covering more than one object.

    Used to tell "there was nothing to choose" from "there was, and the
    project's name matched none of it" — only the second is worth warning
    about.
    """
    if not words:
        return False
    gap = _page_gap(words)
    for row in _rows(words):
        columns = _columns(row, gap)
        if len(columns) < MIN_HEADER_COLUMNS:
            continue
        headings = [_name_tokens(column.text) for column in columns[1:]]
        for i, first in enumerate(headings):
            for second in headings[i + 1:]:
                if first and second and first & second:
                    return True
    return False
