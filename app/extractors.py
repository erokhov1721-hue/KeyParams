import re

GENERAL_CONTRACTOR_ORG_RE = re.compile(r'\b(?:ООО|АО|ЗАО|ПАО|ОАО)\s*«[^»]+»')
PREAMBLE_CITY_RE = re.compile(r'^г\.?\s*Москва\s*$')
FULL_DATE_RE = re.compile(r'\b\d{2}\.\d{2}\.(20\d{2})\b')
QUOTED_DATE_RE = re.compile(r'«\s*\d{1,2}\s*»\s*[а-яё]+\s+(20\d{2})\s*г', re.IGNORECASE)
BUILDING_CLASS_RE = re.compile(
    r'класс[а-яё\s-]{0,20}(бизнес|премиум|комфорт|эконом|элит)', re.IGNORECASE
)
BUILDING_CLASS_REVERSED_RE = re.compile(
    r'(бизнес|премиум|комфорт|эконом|элит)[а-яё\s-]{0,10}класс', re.IGNORECASE
)
BUILDING_CLASS_KEYWORD_RE = re.compile(
    r'бизнес|премиум|комфорт|эконом|элит', re.IGNORECASE
)
WHITESPACE_RE = re.compile(r'\s+')
# A cell holding a value: a number, optionally with a trailing unit of measure.
NUMERIC_CELL_RE = re.compile(
    r'^[-+−]?\d[\d\s .,]*'
    r'(?:\s*(?:м2|м²|кв\.?\s*м\.?|га|шт\.?|эт\.?|этаж(?:а|ей)?)\.?)?$',
    re.IGNORECASE,
)
# Longest label the area extractors accept, in adjacent table cells.
MAX_LABEL_CELLS = 2


def parse_number(text):
    if text is None:
        return None
    t = text.strip()
    if t in ('', '-', '—', '–'):
        return None
    t = WHITESPACE_RE.sub('', t)
    t = t.replace(',', '.')
    t = re.sub(r'[^0-9.\-]', '', t)
    if t in ('', '-', '.', '-.'):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def extract_general_contractor(dgp):
    for para in dgp.paragraphs:
        if 'именуемое в дальнейшем' in para and 'Генподрядчик' in para:
            match = GENERAL_CONTRACTOR_ORG_RE.search(para)
            if match:
                return match.group(0)
    return None


def extract_signing_year(dgp):
    for i, para in enumerate(dgp.paragraphs):
        if PREAMBLE_CITY_RE.match(para.strip()):
            for w in dgp.paragraphs[i:i + 2]:
                m = FULL_DATE_RE.search(w) or QUOTED_DATE_RE.search(w)
                if m:
                    return m.group(1)
            break
    return None


def _first_valid_class_match(para):
    for regex in (BUILDING_CLASS_RE, BUILDING_CLASS_REVERSED_RE):
        for m in regex.finditer(para):
            # If the matched span itself (which includes the "класс" +
            # gap + keyword text) names two or more class keywords, e.g.
            # "классы КОМФОРТ и БИЗНЕС", the gap swallowed an unrelated
            # keyword and this is an enumeration of options rather than a
            # genuine assignment — reject just this match and keep looking,
            # rather than discarding the whole paragraph (which could
            # contain a real assignment plus an unrelated second mention
            # elsewhere, e.g. "...бизнес-класса, ... премиум-класса...").
            if len(BUILDING_CLASS_KEYWORD_RE.findall(m.group(0))) > 1:
                continue
            return m.group(1).capitalize()
    return None


def extract_building_class(dgp, tz):
    for doc in (dgp, tz):
        for para in doc.paragraphs:
            result = _first_valid_class_match(para)
            if result:
                return result
    return None


def _numeric_cell_value(cell):
    """Value of a cell that is a bare number, otherwise None.

    A cell like "м2" is a unit of measure, not a value, even though
    ``parse_number`` happily digs a 2 out of it. Recognising which cells are
    numbers at all is what lets ``_find_area_value`` scan left-to-right from a
    label; the previous implementation had to scan right-to-left to step over
    unit cells, which made it return the rightmost number of a multi-column
    row instead of the one belonging to the matched label.
    """
    text = str(cell or '').strip()
    if not text:
        return None
    if not NUMERIC_CELL_RE.match(text):
        return None
    return parse_number(text)


def _label_end_index(row, must_contain):
    """Index of the last cell of the label matching ``must_contain``, else None.

    The label has to fit in at most ``MAX_LABEL_CELLS`` adjacent non-numeric
    cells — Word tables sometimes split a caption over two cells, but a label
    is never spread across a whole row. Joining the entire row instead (as the
    previous implementation did) matched rows that merely happen to mention
    the tokens in unrelated columns, e.g. a "количество подземных этажей" row
    that also has a "Площадь застройки" column further right.
    """
    for start in range(len(row)):
        for length in range(1, MAX_LABEL_CELLS + 1):
            window = row[start:start + length]
            if len(window) < length:
                break
            if any(_numeric_cell_value(cell) is not None for cell in window):
                break
            joined = ' '.join(str(cell or '') for cell in window).lower()
            if all(token in joined for token in must_contain):
                return start + length - 1
    return None


def _find_area_value(tables, must_contain):
    """First number that follows a cell (or cell pair) labelled with the tokens."""
    for table in tables:
        for row in table:
            if not row:
                continue
            end = _label_end_index(row, must_contain)
            if end is None:
                continue
            for cell in row[end + 1:]:
                value = _numeric_cell_value(cell)
                if value is not None:
                    return value
    return None


def extract_underground_area(tz):
    return _find_area_value(tz.tables, ('площад', 'подземн'))


def extract_aboveground_area(tz):
    return _find_area_value(tz.tables, ('площад', 'надземн'))


def extract_total_area(tz):
    return _find_area_value(tz.tables, ('обща', 'площад'))
