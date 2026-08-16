"""OCR through the recognition engine built into Windows.

Around three hundred times faster than the bundled EasyOCR on this machine —
a second and a bit for a scanned A3 page against six minutes — because
Windows keeps the model resident and does not go through PyTorch to reach it.
It also reads this kind of document more accurately: Cyrillic "СМР" comes back
as Cyrillic rather than as the Latin "CMP" EasyOCR settles for.

So it goes first, and EasyOCR stays behind it for the machines where this
engine, or its Russian language pack, isn't there. Nothing here raises: an
absent package, a missing language and an undecodable image all just mean no
text, exactly as ``ocr.recognize_text`` behaves.
"""

import io
import logging

from PIL import Image

from .ocr_lines import Word, group_into_lines

logger = logging.getLogger(__name__)

LANGUAGE = "ru"

# Windows reads a percent sign as "0/0" often enough that every rate in a
# protocol comes out wrong: "30%" as "300/0", and even the column heading
# "Аванс, %" as "Аванс, 0/0". Replacing left to right puts them all back
# ("300/0" -> "30%"), and a construction protocol has no reason to contain a
# literal "0/0" of its own.
PERCENT_ARTIFACT = "0/0"

# The ways a page can be turned, upright first.
ROTATIONS = (0, 90, 180, 270)

# Enough recognised text to call the page read and stop turning it. A protocol
# page holds thousands of characters; the same page on its side gave twelve.
READS_PROPERLY = 200


def _words_from_result(result) -> list:
    """The recognised words and where each one sits.

    Taken word by word rather than from the engine's own lines: on a table it
    reads column by column, so its lines run down the page and every value
    ends up detached from the label it belongs to.
    """
    words = []
    for line in result.get("lines") or []:
        for word in line.get("words") or []:
            rect = word["bounding_rect"]
            words.append(Word(
                y=rect["y"] + rect["height"] / 2,
                x0=rect["x"],
                x1=rect["x"] + rect["width"],
                height=rect["height"],
                text=word["text"].replace(PERCENT_ARTIFACT, "%"),
            ))
    return words


def _recognize_at(image, angle):
    # Imported here rather than at module scope: the app has to keep working
    # on a machine without the package, and this is the only place that needs
    # it. The import is cached after the first call.
    import winocr

    turned = image if angle == 0 else image.rotate(angle, expand=True)
    return _words_from_result(winocr.recognize_pil_sync(turned, LANGUAGE))


def recognize_page_words(data: bytes) -> list:
    """Positioned words for one page image, read whichever way up it is.

    A scan's real orientation and the /Rotate recorded against it agree far
    less often than one would hope: of two protocols from the same office, one
    came out upright and the other on its side, and the rotation written on
    each was no guide to which. Rather than trust it, the page is simply tried
    every way round and the reading with the most text on it wins — sideways
    text yields a dozen stray characters where the right way up yields
    thousands, so the two are never close.

    The upright try comes first and, on a page that reads properly, is the
    only one made: this costs a second on the pages that need it and nothing
    at all on the pages that don't.
    """
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = source.convert("RGB")
            best = []
            for angle in ROTATIONS:
                words = _recognize_at(image, angle)
                if sum(len(word.text) for word in words) >= READS_PROPERLY:
                    return words
                if len(words) > len(best):
                    best = words
            return best
    except Exception:
        logger.exception("Windows OCR failed")
        return []


def _text_from_result(result) -> str:
    text = "\n".join(group_into_lines(_words_from_result(result)))
    return text.replace(PERCENT_ARTIFACT, "%")


def recognize_text(images: list) -> list:
    """Best-effort OCR over each image's raw bytes, one string per image."""
    return [
        "\n".join(group_into_lines(recognize_page_words(data))) for data in images
    ]


def available() -> bool:
    """Whether this engine can be used at all — the package is installed and
    Windows has the language it needs. Checked so the caller can skip straight
    to the slow engine instead of paying for a failure per page."""
    try:
        import winocr

        return any(
            language.language_tag.lower().startswith(LANGUAGE)
            for language in winocr.OcrEngine.available_recognizer_languages
        )
    except Exception:
        return False
