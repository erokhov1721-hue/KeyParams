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

# How far apart two fragments' vertical centres may sit and still count as
# the same line, as a share of the taller one's height.
LINE_TOLERANCE = 0.6


def group_into_lines(items) -> list:
    """Visual lines from ``(y_center, x_left, height, text)`` fragments.

    Fragments are read in vertical order and cut into a new line whenever the
    gap to the previous one exceeds the tolerance; within a line they are put
    back in left-to-right order, which is what reunites a table row's label
    with the value sitting in the column beside it.
    """
    ordered = sorted(items, key=lambda item: item[0])

    lines = []
    current = []
    current_y = None
    for y_center, x_left, height, text in ordered:
        if current and abs(y_center - current_y) > max(height, 1) * LINE_TOLERANCE:
            lines.append(current)
            current = []
        current.append((x_left, text))
        current_y = y_center
    if current:
        lines.append(current)

    return [
        ' '.join(text for _, text in sorted(line, key=lambda item: item[0]))
        for line in lines
    ]
