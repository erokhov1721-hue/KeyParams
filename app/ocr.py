import easyocr

from .ocr_lines import Word, group_into_lines

_READER = None


def _get_reader():
    global _READER
    if _READER is None:
        _READER = easyocr.Reader(['ru', 'en'], gpu=False)
    return _READER


def _word(detection):
    bbox, text, confidence = detection
    ys = [point[1] for point in bbox]
    xs = [point[0] for point in bbox]
    return Word(
        y=sum(ys) / len(ys),
        x0=min(xs),
        x1=max(xs),
        height=max(ys) - min(ys),
        text=text,
    )


def _group_into_lines(detections):
    """Reassemble EasyOCR's per-phrase detections into visual lines.

    ``readtext`` returns one entry per detected text region, not per visual
    line — a single table row like "Общая площадь м2 67 413" can come back
    as two or three separate detections, which is what
    ``ocr_lines.group_into_lines`` exists to put back together.
    """
    return group_into_lines(_word(det) for det in detections)


def recognize_page_words(data: bytes) -> list:
    """Positioned words for one page image. Empty if the page can't be read.

    The counterpart of ``win_ocr.recognize_page_words``, so that whatever
    needs to know where a word sits — telling one column of a protocol from
    another — works the same whichever engine read the page.
    """
    try:
        detections = _get_reader().readtext(data)
    except Exception:
        return []
    return [_word(det) for det in detections]


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
