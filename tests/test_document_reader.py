import pytest
from app.document_reader import read_docx, DocxReadError
from tests.helpers import (
    Raw,
    document_xml,
    document_xml_from_body,
    make_docx,
    paragraph_xml,
    sdt_xml,
    table_xml,
)


def test_read_paragraphs(tmp_path):
    xml = document_xml(paragraphs=["Привет", "Мир"])
    path = make_docx(tmp_path, xml)
    content = read_docx(path)
    assert content.paragraphs == ["Привет", "Мир"]


def test_read_tables(tmp_path):
    xml = document_xml(tables=[[["a", "b"], ["c", "d"]]])
    path = make_docx(tmp_path, xml)
    content = read_docx(path)
    assert content.tables == [[["a", "b"], ["c", "d"]]]


def test_read_paragraphs_and_tables_together(tmp_path):
    xml = document_xml(paragraphs=["Заголовок"], tables=[[["1", "2"]]])
    path = make_docx(tmp_path, xml)
    content = read_docx(path)
    assert content.paragraphs == ["Заголовок"]
    assert content.tables == [[["1", "2"]]]


def test_read_broken_zip_raises(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip file at all")
    with pytest.raises(DocxReadError):
        read_docx(path)


def test_read_missing_body_raises(tmp_path):
    """A valid XML document.xml without <w:body> must raise DocxReadError."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "</w:document>"
    )
    path = make_docx(tmp_path, xml)
    with pytest.raises(DocxReadError):
        read_docx(path)


def test_read_table_nested_in_cell(tmp_path):
    """Both the outer table and a table nested in one of its cells are found."""
    inner = table_xml([["внутр1", "внутр2"]])
    outer = table_xml([["внешн", Raw(inner)]])
    path = make_docx(tmp_path, document_xml_from_body(outer))
    content = read_docx(path)

    assert content.tables[0] == [["внешн", ""]]
    assert content.tables[1] == [["внутр1", "внутр2"]]
    assert len(content.tables) == 2
    # Cells of a nested table must not leak into top-level paragraphs.
    assert content.paragraphs == []


def test_read_deeply_nested_tables(tmp_path):
    """Nesting deeper than one level is still fully reachable."""
    level3 = table_xml([["L3"]])
    level2 = table_xml([["L2", Raw(level3)]])
    level1 = table_xml([["L1", Raw(level2)]])
    path = make_docx(tmp_path, document_xml_from_body(level1))
    content = read_docx(path)

    flat = [cell for table in content.tables for row in table for cell in row]
    assert "L1" in flat and "L2" in flat and "L3" in flat
    assert len(content.tables) == 3


def test_read_paragraph_inside_sdt(tmp_path):
    """A paragraph wrapped in a content control is still a top-level paragraph."""
    body = sdt_xml(paragraph_xml("Внутри контрола"))
    path = make_docx(tmp_path, document_xml_from_body(body))
    content = read_docx(path)
    assert content.paragraphs == ["Внутри контрола"]


def test_read_table_inside_sdt(tmp_path):
    """A table wrapped in a content control is still found as a table."""
    body = sdt_xml(table_xml([["a", "b"]]))
    path = make_docx(tmp_path, document_xml_from_body(body))
    content = read_docx(path)
    assert content.tables == [[["a", "b"]]]
    assert content.paragraphs == []


def test_paragraph_in_table_cell_is_not_duplicated(tmp_path):
    """Cell paragraphs belong to the table only — never also to paragraphs."""
    xml = document_xml(paragraphs=["Заголовок"], tables=[[["ячейка"]]])
    path = make_docx(tmp_path, xml)
    content = read_docx(path)
    assert content.paragraphs == ["Заголовок"]
    assert content.tables == [[["ячейка"]]]


def test_read_embedded_image(tmp_path):
    xml = document_xml(paragraphs=["Текст"])
    png_bytes = b"\x89PNG\r\n\x1a\nfake-image-data"
    path = make_docx(tmp_path, xml, extra_files={"word/media/image1.png": png_bytes})
    content = read_docx(path)
    assert content.images == [png_bytes]


def test_read_no_images_is_empty_list(tmp_path):
    xml = document_xml(paragraphs=["Текст"])
    path = make_docx(tmp_path, xml)
    content = read_docx(path)
    assert content.images == []


def test_read_ignores_non_image_media(tmp_path):
    xml = document_xml(paragraphs=["Текст"])
    path = make_docx(
        tmp_path, xml,
        extra_files={"word/media/chart1.emf": b"not-supported-format"},
    )
    content = read_docx(path)
    assert content.images == []
