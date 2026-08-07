import pytest
from app.document_reader import read_docx, DocxReadError
from tests.helpers import document_xml, make_docx


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
