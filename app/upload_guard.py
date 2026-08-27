"""Checking that an upload is what its extension claims, not just named like one.

``filename.lower().endswith(".xlsx")`` is a fact about the name a browser
sent along with the request, not about the bytes behind it — nothing stops
an upload named ``smeta.xlsx`` from being anything at all. Every check here
looks at the content instead, and does it cheaply: none of them decompress
or parse the file, only read its own most obvious signature.
"""

import zipfile

# Genuine .docx/.xlsx files compress to a handful of times smaller than they
# expand to — office XML is verbose and repetitive, but it isn't the kind of
# repetition a compressor turns into a thousand-to-one ratio. A zip bomb's
# whole trick is the opposite: a small archive that expands to gigabytes.
# 200:1 is already far more headroom than a real document needs.
MAX_ZIP_EXPANSION_RATIO = 200
# A ceiling in absolute terms too, for an archive whose ratio looks
# plausible only because it is already this large compressed.
MAX_ZIP_UNCOMPRESSED_BYTES = 500 * 1024 * 1024

PDF_SIGNATURE = b"%PDF-"


def _with_position_restored(file_storage):
    """The stream's current position, to be put back when the caller with
    the ``finally`` block below is done — every check here reads from the
    start regardless of where the caller left the stream, and every one
    must leave it exactly as found, or the next thing that reads this
    upload (the size check, the actual save) reads from the wrong place."""
    return file_storage.tell()


def is_office_zip(file_storage) -> bool:
    """Whether ``file_storage`` is a well-formed zip archive — the shape of
    both .docx and .xlsx — that doesn't hide an absurd amount of data behind
    a small upload.

    Reads only the zip's own central directory (a small index at the end of
    the archive), never the compressed data itself: checking a zip bomb by
    decompressing it would be performing the attack in order to detect it.
    """
    position = _with_position_restored(file_storage)
    try:
        file_storage.seek(0)
        try:
            with zipfile.ZipFile(file_storage) as archive:
                infos = archive.infolist()
        except zipfile.BadZipFile:
            return False
        total_uncompressed = sum(info.file_size for info in infos)
        total_compressed = sum(info.compress_size for info in infos) or 1
        if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
            return False
        if total_uncompressed / total_compressed > MAX_ZIP_EXPANSION_RATIO:
            return False
        return True
    finally:
        file_storage.seek(position)


def is_pdf(file_storage) -> bool:
    """Whether ``file_storage`` starts with the PDF file signature."""
    position = _with_position_restored(file_storage)
    try:
        file_storage.seek(0)
        return file_storage.read(len(PDF_SIGNATURE)) == PDF_SIGNATURE
    finally:
        file_storage.seek(position)


def _is_jpeg(header):
    return header.startswith(b"\xff\xd8\xff")


def _is_png(header):
    return header.startswith(b"\x89PNG\r\n\x1a\n")


def _is_webp(header):
    return header[:4] == b"RIFF" and header[8:12] == b"WEBP"


_IMAGE_SIGNATURES = {
    ".jpg": _is_jpeg,
    ".jpeg": _is_jpeg,
    ".png": _is_png,
    ".webp": _is_webp,
}


def is_image(file_storage, ext) -> bool:
    """Whether ``file_storage`` starts with the signature its own claimed
    extension (``ext``, dot included, any case) implies. False for an
    extension this function doesn't know, rather than raising — the caller
    already rejects an unknown extension on its own account."""
    check = _IMAGE_SIGNATURES.get(ext.lower())
    if check is None:
        return False
    position = _with_position_restored(file_storage)
    try:
        file_storage.seek(0)
        header = file_storage.read(16)
        return check(header)
    finally:
        file_storage.seek(position)
