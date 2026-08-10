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


def extract_building_class(dgp, tz):
    for doc in (dgp, tz):
        for para in doc.paragraphs:
            # A paragraph naming two or more class keywords (e.g. "классы
            # КОМФОРТ и БИЗНЕС") is enumerating options, not assigning a
            # class to the building — skip it rather than matching whichever
            # keyword happens to fall within the regex gap.
            if len(BUILDING_CLASS_KEYWORD_RE.findall(para)) > 1:
                continue
            m = BUILDING_CLASS_RE.search(para) or BUILDING_CLASS_REVERSED_RE.search(para)
            if m:
                return m.group(1).capitalize()
    return None


def _find_area_value(tables, must_contain):
    for table in tables:
        for row in table:
            if not row:
                continue
            # Check if any cell in the row contains all required tokens
            label = ' '.join(str(cell or '') for cell in row).lower()
            if all(token in label for token in must_contain):
                for cell in reversed(row[1:]):
                    value = parse_number(cell)
                    if value is not None:
                        return value
    return None


def extract_underground_area(tz):
    return _find_area_value(tz.tables, ('площад', 'подземн'))


def extract_aboveground_area(tz):
    return _find_area_value(tz.tables, ('площад', 'надземн'))


def extract_total_area(tz):
    return _find_area_value(tz.tables, ('обща', 'площад'))
