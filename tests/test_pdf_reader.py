import io

from PIL import Image
from reportlab.lib.pagesizes import A3, A5
from reportlab.pdfgen import canvas

from app import pdf_reader


def _make_pdf(tmp_path, name, pagesize):
    path = tmp_path / name
    c = canvas.Canvas(str(path), pagesize=pagesize)
    c.drawString(40, pagesize[1] - 60, "Performance bond, % 3%")
    c.showPage()
    c.save()
    return path


def _long_edge(png_bytes):
    return max(Image.open(io.BytesIO(png_bytes)).size)


def test_read_pdf_text_returns_the_text_layer(tmp_path):
    path = _make_pdf(tmp_path, "terms.pdf", A5)

    assert "Performance bond" in pdf_reader.read_pdf_text(path)


def test_render_pages_to_images_returns_one_png_per_page(tmp_path):
    path = _make_pdf(tmp_path, "terms.pdf", A5)

    images = pdf_reader.render_pages_to_images(path)

    assert len(images) == 1
    assert images[0].startswith(b"\x89PNG")


def test_render_pages_caps_long_edge_for_a_large_page(tmp_path):
    # A3 at the default resolution renders ~3300px tall, above what the API
    # accepts, so it would be downscaled server-side anyway.
    path = _make_pdf(tmp_path, "big.pdf", A3)

    images = pdf_reader.render_pages_to_images(path)

    assert _long_edge(images[0]) <= pdf_reader.MAX_IMAGE_LONG_EDGE


def test_render_pages_does_not_upscale_a_small_page(tmp_path):
    path = _make_pdf(tmp_path, "small.pdf", A5)

    images = pdf_reader.render_pages_to_images(path)

    assert _long_edge(images[0]) < pdf_reader.MAX_IMAGE_LONG_EDGE


def test_render_pages_keeps_aspect_ratio_when_capping(tmp_path):
    path = _make_pdf(tmp_path, "big.pdf", A3)

    images = pdf_reader.render_pages_to_images(path)

    width, height = Image.open(io.BytesIO(images[0])).size
    page_ratio = A3[0] / A3[1]
    assert abs(width / height - page_ratio) < 0.01
