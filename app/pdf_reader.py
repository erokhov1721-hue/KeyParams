import io

import pdfplumber


class PdfReadError(Exception):
    pass


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
                page.to_image(resolution=resolution).original.save(buf, format='PNG')
                images.append(buf.getvalue())
    except Exception as e:
        raise PdfReadError(f"Cannot read {path}: {e}") from e
    return images
