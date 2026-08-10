import io
import zipfile

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)

RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '</Relationships>'
)


class Raw(str):
    """Marker for a cell whose value is literal XML rather than plain text.

    Lets a test put arbitrary content (e.g. a nested ``<w:tbl>``) inside a
    table cell: ``table_xml([[ "label", Raw(table_xml(...)) ]])``.
    """


def paragraph_xml(text):
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def table_xml(rows):
    trs = ""
    for row in rows:
        tcs = ""
        for cell in row:
            inner = cell if isinstance(cell, Raw) else paragraph_xml(cell)
            tcs += f"<w:tc>{inner}</w:tc>"
        trs += f"<w:tr>{tcs}</w:tr>"
    return f"<w:tbl>{trs}</w:tbl>"


def sdt_xml(inner_xml):
    """Wrap literal XML in a content control, as real Word documents do."""
    return f"<w:sdt><w:sdtPr/><w:sdtContent>{inner_xml}</w:sdtContent></w:sdt>"


# Backwards-compatible private aliases (kept so older call sites keep working).
_paragraph_xml = paragraph_xml
_table_xml = table_xml


def document_xml_from_body(body_xml):
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body_xml}</w:body></w:document>'
    )


def document_xml(paragraphs=(), tables=()):
    body = "".join(paragraph_xml(p) for p in paragraphs)
    body += "".join(table_xml(t) for t in tables)
    return document_xml_from_body(body)


def build_docx_bytes(doc_xml, extra_files=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc_xml)
        for name, data in (extra_files or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def make_docx(tmp_path, doc_xml, filename="test.docx", extra_files=None):
    path = tmp_path / filename
    path.write_bytes(build_docx_bytes(doc_xml, extra_files=extra_files))
    return path
