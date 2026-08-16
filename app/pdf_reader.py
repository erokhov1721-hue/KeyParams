import io

import pdfplumber
from PIL import Image

# Claude accepts images up to this many pixels on the long edge and
# downscales anything bigger itself. An A3 protocol page renders well past
# it, so cap it here instead: resampling once with a good filter keeps the
# table's small print sharper than letting it be resized twice.
MAX_IMAGE_LONG_EDGE = 2576


class PdfReadError(Exception):
    pass


def _cap_long_edge(image, max_long_edge=MAX_IMAGE_LONG_EDGE):
    """Shrink to fit ``max_long_edge``, preserving aspect ratio.

    Images already within the limit are returned untouched — upscaling a
    small page would only invent detail.
    """
    long_edge = max(image.size)
    if long_edge <= max_long_edge:
        return image
    scale = max_long_edge / long_edge
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.LANCZOS)


def read_pdf_text(path) -> str:
    """All text from every page, joined with newlines.

    An empty string means the PDF has no text layer at all — e.g. a page
    that's really a scanned image — which tells the caller to fall back to
    OCR rather than that there's nothing on the page.
    """
    try:
        with pdfplumber.open(path) as pdf:
            pages_text = [page.extract_text() or '' for page in pdf.pages]
    except Exception as e:
        raise PdfReadError(f"Cannot read {path}: {e}") from e
    return '\n'.join(pages_text)


def render_pages_to_images(path, resolution=200, max_long_edge=MAX_IMAGE_LONG_EDGE) -> list:
    """PNG bytes for every page, for reading a scan that has no text layer.

    ``max_long_edge`` exists for the API, which won't take a bigger image.
    Pass None for local OCR: the shrink costs it the small print. On a real
    A3 protocol, capping the page turned "30%" into text the extractor could
    no longer recognise as a rate at all.
    """
    images = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                buf = io.BytesIO()
                # Whichever way up the page comes out is left to the reader of
                # it: a scan's real orientation and the /Rotate recorded
                # against it agree far less often than one would hope, and the
                # recogniser can simply try the page every way round and keep
                # what reads (see ``win_ocr.recognize_page_words``).
                rendered = page.to_image(resolution=resolution).original
                if max_long_edge is not None:
                    rendered = _cap_long_edge(rendered, max_long_edge)
                rendered.save(buf, format='PNG')
                images.append(buf.getvalue())
    except Exception as e:
        raise PdfReadError(f"Cannot read {path}: {e}") from e
    return images
