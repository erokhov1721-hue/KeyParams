import io
import zipfile

from app import upload_guard


def _zip_bytes(entries):
    """A minimal real zip archive with the given ``{name: content}`` files —
    exercising the actual zip format rather than a hand-rolled stand-in."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buf.getvalue()


def _docx_like_bytes():
    return _zip_bytes({
        "[Content_Types].xml": "<Types/>",
        "word/document.xml": "<document>Привет, мир</document>" * 20,
    })


def test_a_real_office_zip_passes():
    stream = io.BytesIO(_docx_like_bytes())

    assert upload_guard.is_office_zip(stream) is True


def test_a_file_that_is_not_a_zip_at_all_fails():
    stream = io.BytesIO(b"not a zip file, just some text pretending to be one")

    assert upload_guard.is_office_zip(stream) is False


def test_an_empty_upload_fails():
    stream = io.BytesIO(b"")

    assert upload_guard.is_office_zip(stream) is False


def test_a_highly_compressible_payload_disguised_as_office_fails():
    # A real .docx/.xlsx doesn't compress much further than office XML
    # already does — a huge run of one repeated byte is the shape a zip
    # bomb takes, not a real document.
    bomb = _zip_bytes({"a.xml": "A" * 50_000_000})
    stream = io.BytesIO(bomb)

    assert upload_guard.is_office_zip(stream) is False


def test_checking_leaves_the_stream_position_where_it_found_it():
    stream = io.BytesIO(_docx_like_bytes())
    stream.seek(7)

    upload_guard.is_office_zip(stream)

    assert stream.tell() == 7


def test_a_pdf_signature_passes():
    stream = io.BytesIO(b"%PDF-1.7\n%rest of a real pdf would go here")

    assert upload_guard.is_pdf(stream) is True


def test_text_named_like_a_pdf_fails():
    stream = io.BytesIO(b"this is not a pdf")

    assert upload_guard.is_pdf(stream) is False


def test_a_jpeg_signature_passes_as_jpg_or_jpeg():
    stream = io.BytesIO(b"\xff\xd8\xff\xe0rest of a jpeg")

    assert upload_guard.is_image(stream, ".jpg") is True
    assert upload_guard.is_image(stream, ".JPEG") is True


def test_a_png_signature_passes():
    stream = io.BytesIO(b"\x89PNG\r\n\x1a\nrest of a png")

    assert upload_guard.is_image(stream, ".png") is True


def test_a_webp_signature_passes():
    stream = io.BytesIO(b"RIFF\x00\x00\x00\x00WEBPVP8 ")

    assert upload_guard.is_image(stream, ".webp") is True


def test_a_png_disguised_with_a_jpg_extension_fails():
    stream = io.BytesIO(b"\x89PNG\r\n\x1a\nrest of a png")

    assert upload_guard.is_image(stream, ".jpg") is False


def test_an_unknown_extension_fails_rather_than_raising():
    stream = io.BytesIO(b"\xff\xd8\xff\xe0")

    assert upload_guard.is_image(stream, ".gif") is False
