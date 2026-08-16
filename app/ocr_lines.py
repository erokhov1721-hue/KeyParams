"""Reassembling OCR output into visual lines.

Every OCR engine hands back positioned fragments rather than the lines a
reader sees: EasyOCR one entry per detected region, the Windows engine one
per column of a table. Both need the same treatment — group by vertical
position, order left to right within a group — to produce the "one string per
line" shape the extractors are written against.

Lives apart from the engines so that using one doesn't drag in the other's
dependencies: importing ``ocr`` costs a PyTorch load, which is not something
the Windows engine should have to pay for.
"""

from collections import namedtuple

# A recognised word and where it sits on the page. The right edge is carried
# as well as the left because a protocol covering two objects puts their
# figures in two columns, and telling those apart is a question of horizontal
# position and nothing else.
Word = namedtuple("Word", "y x0 x1 height text")

# How far apart two words' vertical centres may sit and still count as the
# same line, as a share of the taller one's height.
LINE_TOLERANCE = 0.6


def group_into_lines(words) -> list:
    """Visual lines from positioned words.

    Words are read in vertical order and cut into a new line whenever the gap
    to the previous one exceeds the tolerance; within a line they are put back
    in left-to-right order, which is what reunites a table row's label with
    the value sitting in the column beside it.
    """
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

    return [
        ' '.join(word.text for word in sorted(line, key=lambda word: word.x0))
        for line in lines
    ]
