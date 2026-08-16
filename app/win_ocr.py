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

from .ocr_lines import group_into_lines

logger = logging.getLogger(__name__)

LANGUAGE = "ru"

# Windows reads a percent sign as "0/0" often enough that every rate in a
# protocol comes out wrong: "30%" as "300/0", and even the column heading
# "Аванс, %" as "Аванс, 0/0". Replacing left to right puts them all back
# ("300/0" -> "30%"), and a construction protocol has no reason to contain a
# literal "0/0" of its own.
PERCENT_ARTIFACT = "0/0"


def _text_from_result(result) -> str:
    """Lay a recognition result back out as the page reads.

    Rebuilt from the individual words rather than taken from the engine's own
    lines: on a table it reads column by column, so its lines run down the
    page and every value ends up detached from the label it belongs to.
    """
    fragments = []
    for line in result.get("lines") or []:
        for word in line.get("words") or []:
            rect = word["bounding_rect"]
            fragments.append((
                rect["y"] + rect["height"] / 2,
                rect["x"],
                rect["height"],
                word["text"],
            ))

    text = "\n".join(group_into_lines(fragments))
    return text.replace(PERCENT_ARTIFACT, "%")


def _recognize_one(data: bytes) -> str:
    # Imported here rather than at module scope: the app has to keep working
    # on a machine without the package, and this is the only place that needs
    # it. The import is cached after the first call.
    import winocr

    with Image.open(io.BytesIO(data)) as source:
        image = source.convert("RGB")
        result = winocr.recognize_pil_sync(image, LANGUAGE)
    return _text_from_result(result)


def recognize_text(images: list) -> list:
    """Best-effort OCR over each image's raw bytes, one string per image."""
    texts = []
    for data in images:
        try:
            texts.append(_recognize_one(data))
        except Exception:
            logger.exception("Windows OCR failed")
            texts.append("")
    return texts


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
