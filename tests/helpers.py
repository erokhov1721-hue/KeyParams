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


def _paragraph_xml(text):
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _table_xml(rows):
    trs = ""
    for row in rows:
        tcs = "".join(f"<w:tc>{_paragraph_xml(cell)}</w:tc>" for cell in row)
        trs += f"<w:tr>{tcs}</w:tr>"
    return f"<w:tbl>{trs}</w:tbl>"


def document_xml(paragraphs=(), tables=()):
    body = "".join(_paragraph_xml(p) for p in paragraphs)
    body += "".join(_table_xml(t) for t in tables)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body}</w:body></w:document>'
    )


def build_docx_bytes(doc_xml):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


def make_docx(tmp_path, doc_xml, filename="test.docx"):
    path = tmp_path / filename
    path.write_bytes(build_docx_bytes(doc_xml))
    return path
