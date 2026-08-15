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


def _cap_long_edge(image):
    """Shrink to fit MAX_IMAGE_LONG_EDGE, preserving aspect ratio.

    Images already within the limit are returned untouched — upscaling a
    small page would only invent detail.
    """
    long_edge = max(image.size)
    if long_edge <= MAX_IMAGE_LONG_EDGE:
        return image
    scale = MAX_IMAGE_LONG_EDGE / long_edge
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


def render_pages_to_images(path, resolution=200) -> list:
    """PNG bytes for every page, for OCR when there's no text layer."""
    images = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                buf = io.BytesIO()
                rendered = page.to_image(resolution=resolution).original
                _cap_long_edge(rendered).save(buf, format='PNG')
                images.append(buf.getvalue())
    except Exception as e:
        raise PdfReadError(f"Cannot read {path}: {e}") from e
    return images
