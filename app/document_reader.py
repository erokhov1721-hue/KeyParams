import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _qn(tag):
    return W_NS + tag


@dataclass
class DocxContent:
    paragraphs: list
    tables: list


class DocxReadError(Exception):
    pass


def read_docx(path) -> DocxContent:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            with z.open('word/document.xml') as f:
                tree = ElementTree.parse(f)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise DocxReadError(f"Cannot read {path}: {e}") from e

    body = tree.getroot().find(_qn('body'))

    paragraphs = []
    tables = []

    for child in body:
        if child.tag == _qn('p'):
            text = ''.join(t.text or '' for t in child.iter(_qn('t')))
            paragraphs.append(text)
        elif child.tag == _qn('tbl'):
            rows = []
            for tr in child.findall(_qn('tr')):
                cells = []
                for tc in tr.findall(_qn('tc')):
                    cell_text = ''.join(t.text or '' for t in tc.iter(_qn('t')))
                    cells.append(cell_text)
                rows.append(cells)
            tables.append(rows)

    return DocxContent(paragraphs=paragraphs, tables=tables)
