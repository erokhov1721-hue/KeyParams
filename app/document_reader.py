import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
MC_NS = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'


def _qn(tag):
    return W_NS + tag


P = _qn('p')
TBL = _qn('tbl')
TR = _qn('tr')
TC = _qn('tc')
T = _qn('t')
ALTERNATE_CONTENT = MC_NS + 'AlternateContent'
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.tif')


@dataclass
class DocxContent:
    paragraphs: list
    tables: list
    images: list = field(default_factory=list)


class DocxReadError(Exception):
    pass


def _children(element):
    """Children of ``element`` that should be descended into.

    ``<mc:AlternateContent>`` carries several equivalent renderings of the
    same content (``<mc:Choice>`` / ``<mc:Fallback>``); walking all of them
    would report the same text twice, so only the first branch is visited.
    """
    if element.tag == ALTERNATE_CONTENT:
        return list(element)[:1]
    return list(element)


def _text_of(element, stop_tags=()):
    """Concatenate every ``<w:t>`` under ``element``, skipping ``stop_tags``.

    Used for both paragraph text and table-cell text. Cells pass
    ``stop_tags=(TBL,)`` so that a table nested inside a cell contributes its
    text only through its own entry in ``DocxContent.tables``, never twice.
    """
    parts = []

    def walk(el):
        for child in _children(el):
            if child.tag in stop_tags:
                continue
            if child.tag == T:
                parts.append(child.text or '')
            else:
                walk(child)

    walk(element)
    return ''.join(parts)


def _find_wrapped(parent, tag, stop_tags):
    """Yield descendants of ``parent`` tagged ``tag``.

    Descends transparently through wrapper elements (``<w:sdt>``,
    ``<w:sdtContent>``, ``<w:customXml>``, ...) but never into a matched
    element nor into anything listed in ``stop_tags`` — that is what keeps a
    nested table's rows from being mistaken for the outer table's rows.
    """
    for child in _children(parent):
        if child.tag == tag:
            yield child
        elif child.tag in stop_tags:
            continue
        else:
            yield from _find_wrapped(child, tag, stop_tags)


def _extract_table(tbl, tables):
    """Append ``tbl`` to ``tables``, then append its nested tables as well.

    Nested tables are flattened into separate top-level entries: nothing
    downstream needs the nesting structure, only "does some row somewhere
    contain these tokens".
    """
    rows = []
    nested = []
    for tr in _find_wrapped(tbl, TR, stop_tags=(TBL, TC, P)):
        cells = []
        for tc in _find_wrapped(tr, TC, stop_tags=(TBL, P)):
            cells.append(_text_of(tc, stop_tags=(TBL,)))
            nested.extend(_find_wrapped(tc, TBL, stop_tags=(TBL, P)))
        rows.append(cells)
    tables.append(rows)
    for sub in nested:
        _extract_table(sub, tables)


def _walk(element, paragraphs, tables):
    """Collect paragraphs and tables from anywhere under ``element``.

    Every ``<w:p>`` and every ``<w:tbl>`` is reachable, at any nesting depth
    and through any wrapping element, with no double counting: a ``<w:tbl>``
    is handed to ``_extract_table`` and is *not* descended into here, so the
    paragraphs living in its cells surface as cell text rather than as
    top-level paragraphs.
    """
    for child in _children(element):
        if child.tag == P:
            paragraphs.append(_text_of(child))
        elif child.tag == TBL:
            _extract_table(child, tables)
        else:
            _walk(child, paragraphs, tables)


def read_docx(path) -> DocxContent:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            with z.open('word/document.xml') as f:
                tree = ElementTree.parse(f)
            images = [
                z.read(name)
                for name in z.namelist()
                if name.startswith('word/media/') and name.lower().endswith(IMAGE_EXTENSIONS)
            ]
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise DocxReadError(f"Cannot read {path}: {e}") from e

    body = tree.getroot().find(_qn('body'))
    if body is None:
        raise DocxReadError(f"Cannot read {path}: no <w:body> element in word/document.xml")

    paragraphs = []
    tables = []
    _walk(body, paragraphs, tables)

    return DocxContent(paragraphs=paragraphs, tables=tables, images=images)
