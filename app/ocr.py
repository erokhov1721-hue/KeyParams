import easyocr

_READER = None


def _get_reader():
    global _READER
    if _READER is None:
        _READER = easyocr.Reader(['ru', 'en'], gpu=False)
    return _READER


def _line_key(detection):
    bbox, text, confidence = detection
    ys = [point[1] for point in bbox]
    xs = [point[0] for point in bbox]
    return sum(ys) / len(ys), min(xs), max(ys) - min(ys)


def _group_into_lines(detections):
    """Reassemble EasyOCR's per-phrase detections into visual lines.

    ``readtext`` returns one entry per detected text region, not per visual
    line — a single table row like "Общая площадь м2 67 413" can come back
    as two or three separate detections. Grouping by vertical position (and
    then ordering left-to-right within a group) reconstructs the same
    "one string per line" shape that the rest of the extraction pipeline
    (built for plain paragraph text) already expects.
    """
    items = sorted(
        ((*_line_key(det), det[1]) for det in detections),
        key=lambda item: item[0],
    )

    lines = []
    current = []
    current_y = None
    for y_center, x_left, height, text in items:
        if current and abs(y_center - current_y) > max(height, 1) * 0.6:
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


def recognize_text(images: list) -> list:
    """Best-effort OCR over each image's raw bytes.

    Never raises: an image that can't be decoded, or a reader that fails to
    initialise (e.g. no network for the one-time model download), both just
    contribute an empty string for that image, so a caller never needs its
    own try/except around this.
    """
    texts = []
    for data in images:
        try:
            detections = _get_reader().readtext(data)
            texts.append('\n'.join(_group_into_lines(detections)))
        except Exception:
            texts.append('')
    return texts
