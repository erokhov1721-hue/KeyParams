"""Reassembling OCR output into visual lines, and tidying what the engines
misread the same way.

Every OCR engine hands back positioned fragments rather than the lines a
reader sees: EasyOCR one entry per detected region, the Windows engine one
per column of a table. Both need the same treatment — group by vertical
position, order left to right within a group — to produce the "one string per
line" shape the extractors are written against.

``normalize_words`` fixes the misreadings the engines share: a percent sign
read as "0/0", and Cyrillic letters read as their Latin look-alikes ("CMP"
for «СМР»). It runs on the engines' words before anything else sees them.

Lives apart from the engines so that using one doesn't drag in the other's
dependencies: importing ``ocr`` costs a PyTorch load, which is not something
the Windows engine should have to pay for.
"""

import re
from collections import namedtuple

# A recognised word and where it sits on the page. The right edge is carried
# as well as the left because a protocol covering two objects puts their
# figures in two columns, and telling those apart is a question of horizontal
# position and nothing else.
Word = namedtuple("Word", "y x0 x1 height text")

# How far apart two words' vertical centres may sit and still count as the
# same line, as a share of the taller one's height.
LINE_TOLERANCE = 0.6

# A percent sign read as "0/0" — often enough that every rate in a protocol
# comes out wrong: "30%" as "300/0", and even the column heading "Аванс, %" as
# "Аванс, 0/0". Replacing left to right puts them all back ("300/0" -> "30%"),
# and a construction protocol has no reason to contain a literal "0/0".
PERCENT_ARTIFACT = "0/0"

# Latin letters drawn exactly like a Cyrillic one, and that Cyrillic letter.
# An engine reading a Russian page puts the Latin one in often enough:
# «СМР» comes back as "CMP", «Не включено» as "He включено".
LATIN_LOOKALIKES = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
})
_LOOKALIKE_LETTERS = frozenset("ABCEHKMOPTXacepoxy")
_LATIN_RE = re.compile(r"[A-Za-z]")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _rows(words):
    """Words grouped into visual lines, top to bottom; within a line, in the
    order they came."""
    ordered = sorted(words, key=lambda word: word.y)

    lines = []
    current = []
    current_y = None
    for word in ordered:
        if current and abs(word.y - current_y) > max(word.height, 1) * LINE_TOLERANCE:
            lines.append(current)
            current = []
        current.append(word)
        current_y = word.y
    if current:
        lines.append(current)
    return lines


def group_into_lines(words) -> list:
    """Visual lines from positioned words.

    Words are read in vertical order and cut into a new line whenever the gap
    to the previous one exceeds the tolerance; within a line they are put back
    in left-to-right order, which is what reunites a table row's label with
    the value sitting in the column beside it.
    """
    return [
        ' '.join(word.text for word in sorted(line, key=lambda word: word.x0))
        for line in _rows(words)
    ]


def _is_lookalike_only(text):
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and all(ch in _LOOKALIKE_LETTERS for ch in letters)


def normalize_text(text, line_is_cyrillic=False):
    """One word as the page meant it.

    - "0/0" is a percent sign;
    - a word mixing Latin and Cyrillic letters gets its Latin look-alikes
      turned Cyrillic: no Russian word is spelt half in Latin;
    - a word made only of look-alikes ("CMP") is turned Cyrillic when the
      line around it is mostly Cyrillic. A word with any other Latin letter
      — "bond", "performance", "MR" — is genuinely Latin and stays as it is.
    """
    text = text.replace(PERCENT_ARTIFACT, "%")
    has_latin = bool(_LATIN_RE.search(text))
    if not has_latin:
        return text
    if _CYRILLIC_RE.search(text):
        return text.translate(LATIN_LOOKALIKES)
    if line_is_cyrillic and _is_lookalike_only(text):
        return text.translate(LATIN_LOOKALIKES)
    return text


def _mostly_cyrillic(line):
    text = " ".join(word.text for word in line)
    return len(_CYRILLIC_RE.findall(text)) > len(_LATIN_RE.findall(text))


def normalize_words(words) -> list:
    """The same words, in the same order, with ``normalize_text`` applied —
    each judged against the line it sits on."""
    words = list(words)
    cyrillic_line = {}
    for line in _rows(words):
        verdict = _mostly_cyrillic(line)
        for word in line:
            cyrillic_line[id(word)] = verdict
    return [
        word._replace(text=normalize_text(word.text, cyrillic_line[id(word)]))
        for word in words
    ]
