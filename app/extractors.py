import math
import re
from decimal import Decimal, InvalidOperation

GENERAL_CONTRACTOR_ORG_RE = re.compile(r'\b(?:ООО|АО|ЗАО|ПАО|ОАО)\s*«[^»]+»')
# A contract that names the Генподрядчик's legal form in full rather than by
# its usual abbreviation — "Акционерное общество «Фодд»" instead of "АО
# «Фодд»" — never matches the pattern above at all, so this is a separate
# fallback rather than an extra alternative inside it: adding the full forms
# there would make one of them win over an abbreviation appearing later in
# the same sentence, changing what every contract that already has both
# gets back.
ORG_FULL_FORM_TO_ABBREVIATION = {
    'Общество с ограниченной ответственностью': 'ООО',
    'Акционерное общество': 'АО',
    'Закрытое акционерное общество': 'ЗАО',
    'Публичное акционерное общество': 'ПАО',
    'Открытое акционерное общество': 'ОАО',
}
GENERAL_CONTRACTOR_ORG_FULL_RE = re.compile(
    r'\b(' + '|'.join(re.escape(form) for form in ORG_FULL_FORM_TO_ABBREVIATION)
    + r')\s*«([^»]+)»'
)
# The title page always states the object's address as "расположенный по
# адресу: г. <city>, <district boilerplate>, ул. <street>, <plot-number
# boilerplate> NN[/NN] (кадастровый номер ...)." — only the city and the
# street name + plot number are wanted, e.g. "г. Москва, ул. Верейская 29/35".
ADDRESS_ANCHOR_RE = re.compile(r'расположенн\w*\s+по\s+адресу\s*:?', re.IGNORECASE)
ADDRESS_CITY_RE = re.compile(r'\bг\.?\s*([А-ЯЁ][а-яё]+)')
# The kinds of thoroughfare that turn up in these contracts, abbreviated and
# spelled out. Only "ул." was recognised until a contract came through for an
# object on проспект Мира: the name never matched, so the whole address came
# back empty even though the city and the street were both plainly there.
ADDRESS_STREET_TYPES = (
    r'ул|улица|пр-?кт|просп|проспект|пр-?д|проезд|пер|переулок|ш|шоссе|'
    r'наб|набережная|б-?р|бульвар|пл|площадь|туп|тупик|аллея|линия'
)
ADDRESS_STREET_RE = re.compile(
    rf'\b(({ADDRESS_STREET_TYPES})\.?)\s+([^,()\n]+)', re.IGNORECASE,
)
# Some contracts name the street before its type instead of after — "Никольская
# ул." rather than "ул. Никольская" — tried only once the order above finds
# nothing, so a document using the usual order never has its match changed.
ADDRESS_STREET_REVERSED_RE = re.compile(
    rf'([^,()\n]+?)\s+(({ADDRESS_STREET_TYPES})\.?)(?=[,.\n]|$)', re.IGNORECASE,
)
# The «Объект» term's own definition, for a contract that names the address
# without "расположенный" in front of it — "«Объект» - «...» по адресу: г.
# Москва, ...". Scoped to a paragraph that names «Объект» itself so a
# party's own postal address elsewhere in the contract (e.g. in the
# "Уведомления" section) is never mistaken for the Объект's.
OBJECT_TERM_ADDRESS_RE = re.compile(r'«Объект».*?по\s+адресу\s*:?', re.IGNORECASE | re.DOTALL)
# A contract that builds the Объект up out of several numbered construction
# stages — "Этап 1" defining «Объект 1», "Этап 2" defining «Объект 2», each
# with its own address, and a separate clause saying «Объект» means all of
# them "в совокупности" — has no single address of its own to read off; the
# passport shows the last (largest) stage's address rather than an earlier,
# smaller stage that merely happens to be defined — and addressed — first in
# the document. Each stage's own defining sentence ends "...(по тексту –
# «Объект N»)."
STAGE_OBJECT_LABEL_RE = re.compile(r'по\s+тексту\s*[–—-]\s*«Объект\s*(\d+)»', re.IGNORECASE)
PLAIN_ADDRESS_RE = re.compile(r'по\s+адресу\s*:?', re.IGNORECASE)
# The house or plot number, and only when it comes directly after the street
# name. Anchored rather than searched: the same sentence usually ends with a
# cadastral number ("кадастровый номер земельного участка 77:02:0019010:7241"),
# and a free search would happily report its first digits as the house number.
# An address with no number at all is normal — the plot is then identified by
# that cadastral number instead — so a missing number is not a failure.
ADDRESS_PLOT_RE = re.compile(
    r'^\s*,\s*(?:вл|влд|влад|владение|д|дом|уч|участок|стр|строение)?\.?\s*'
    r'(\d+[А-Яа-я]?(?:/\d+)?)\b',
    re.IGNORECASE,
)
PREAMBLE_CITY_RE = re.compile(r'^г\.?\s*Москва\s*$', re.IGNORECASE)
FULL_DATE_RE = re.compile(r'\b\d{2}\.\d{2}\.(20\d{2})\b')
QUOTED_DATE_RE = re.compile(r'«\s*\d{1,2}\s*»\s*[а-яё]+\s+(20\d{2})\s*г', re.IGNORECASE)
# A cover-page line that is just the year on its own, e.g. "2025 год" or
# "2025 г." — a common convention below the parties' names on a Russian
# contract's title page, used as a fallback when there's no dated preamble.
STANDALONE_YEAR_RE = re.compile(r'^(20\d{2})\s*(?:год|г\.?)\s*$', re.IGNORECASE)
# A cover page that names the year alongside the city on the same line —
# "Москва, 2024 год" — rather than as a line on its own (STANDALONE_YEAR_RE
# above) or as part of a dated preamble.
CITY_YEAR_LINE_RE = re.compile(r'^[А-ЯЁ][а-яё]+\s*,\s*(20\d{2})\s*(?:год|г\.?)\s*$', re.IGNORECASE)
PRICE_RE = re.compile(
    r'Цена\s+(?:Работ|Договора)\b.{0,150}?составляет\s+(?:сумму\s+)?'
    r'([\d\s\xa0]+[.,]\d{2})\s*руб',
    re.IGNORECASE,
)
# A contract that splits the price into a VAT-inclusive and a VAT-exempt
# part instead of stating one total up front — "...состоит из двух частей:
# – части, облагаемой НДС, составляющей сумму в размере X руб. ... - части,
# не облагаемой НДС, ..., составляющей сумму в размере Y руб." The total is
# the sum of every part that follows the anchor, stopping at the first
# paragraph that names none — later in the same section other rouble
# figures turn up (compensation formulas, material-price thresholds) that
# are not parts of this sum.
SPLIT_PRICE_ANCHOR_RE = re.compile(r'состоит\s+из\s+\S+\s+частей', re.IGNORECASE)
SPLIT_PRICE_PART_RE = re.compile(
    r'сумму\s+в\s+размере\s+([\d\s\xa0]+[.,]\d{2})\s*руб', re.IGNORECASE,
)
BUILDING_CLASS_RE = re.compile(
    r'класс[а-яё\s«»"\'-]{0,20}(бизнес|премиум|комфорт|эконом|элит)', re.IGNORECASE
)
BUILDING_CLASS_REVERSED_RE = re.compile(
    r'(бизнес|премиум|комфорт|эконом|элит)[а-яё\s«»"\'-]{0,10}класс', re.IGNORECASE
)
BUILDING_CLASS_KEYWORD_RE = re.compile(
    r'бизнес|премиум|комфорт|эконом|элит', re.IGNORECASE
)
WHITESPACE_RE = re.compile(r'\s+')
# A cell holding a value: a number, optionally followed by a unit of measure.
# Group 1 captures *only* the numeric portion, so a unit's own digits ("м2")
# never end up inside it — parse_number now refuses a string with anything
# but a number in it rather than gluing them together, but a caller still
# wants the number even when a unit sits right after it, not a None because
# the cell as a whole doesn't parse as one. The lazy quantifier is what lets
# the unit alternation claim its own text instead of the number swallowing it.
NUMERIC_CELL_RE = re.compile(
    r'^([-+−]?\d[\d\s .,]*?)'
    r'\s*(?:м2|м²|кв\.?\s*м\.?|га|шт\.?|эт\.?|этаж(?:а|ей)?)?\.?$',
    re.IGNORECASE,
)
# Longest label the area extractors accept, in adjacent table cells.
MAX_LABEL_CELLS = 2
# "Площадь застройки" (building-footprint area) is a distinct, named
# real-estate metric that shares tokens with underground/aboveground/total
# area labels but must never be picked in their place.
FOOTPRINT_EXCLUSION = ('застройки',)

# A signed number written the way these documents actually write one:
# digits, optional thousand-separating whitespace, and at most one decimal
# separator (comma or dot). Nothing else — a stray letter or a truncated
# exponent leaves characters unconsumed, which fails the full-string match.
_NUMBER_BODY_RE = re.compile(r'^\d[\d\s ]*([.,]\d+)?$')
# The ASCII hyphen and the real minus sign (U+2212) a document might use for
# a negative value — not an em/en dash, which these documents use on its own
# to mean "no value" (see the sentinel check below) rather than as a sign.
_MINUS_CHARS = '-−'


def _parsed_number_body(text):
    """(body, negative) — ``text`` normalized down to a plain numeral
    string and its sign, or (None, None) if it doesn't name one number
    cleanly. Shared by ``parse_number`` and ``parse_money``, which only
    differ in what they convert the body to."""
    if text is None:
        return None, None
    t = text.strip()
    if t in ('', '-', '—', '–', '−'):
        return None, None
    negative = t[0] in _MINUS_CHARS
    body = t[1:].strip() if negative or t[0] == '+' else t
    if not _NUMBER_BODY_RE.match(body):
        return None, None
    return WHITESPACE_RE.sub('', body).replace(',', '.'), negative


def parse_number(text):
    """The number ``text`` names in full, or None if it doesn't name one
    cleanly.

    Parses the whole string rather than digging a number out of whatever is
    in it: text with a stray letter in the middle ("12abc34"), a truncated
    exponent ("1e400"), two decimal points, or anything else that isn't
    recognisably one number is refused rather than guessed at — a wrong
    number is worse than a missing one. A leading typographic minus is
    still read as negative, and a result too large to be a real quantity
    (``inf``) is refused the same as anything else that doesn't parse.

    Returns ``float`` — fine for a physical quantity (an area, a volume, a
    coefficient), which is approximate by nature. Money goes through
    ``parse_money`` instead: summed across many estimate lines, a float's
    binary rounding compounds in a way a single area or percentage never
    accumulates enough terms to.
    """
    body, negative = _parsed_number_body(text)
    if body is None:
        return None
    try:
        value = float(body)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return -value if negative else value


def parse_money(text):
    """Like ``parse_number``, but returns ``Decimal`` — for a rouble
    amount, which must not pick up a binary float's rounding on the way in
    from a document on top of whatever Excel's own float64 storage already
    cost it. See ``parse_number`` for what counts as a cleanly-written
    number; the two share that rule and differ only in what they convert
    the body to.
    """
    body, negative = _parsed_number_body(text)
    if body is None:
        return None
    try:
        value = Decimal(body)
    except InvalidOperation:
        return None
    return -value if negative else value


def extract_general_contractor(dgp):
    for para in dgp.paragraphs:
        if 'именуемое в дальнейшем' in para and 'Генподрядчик' in para:
            match = GENERAL_CONTRACTOR_ORG_RE.search(para)
            if match:
                return match.group(0)
            match = GENERAL_CONTRACTOR_ORG_FULL_RE.search(para)
            if match:
                abbreviation = ORG_FULL_FORM_TO_ABBREVIATION[match.group(1)]
                return f"{abbreviation} «{match.group(2)}»"
    return None


def _staged_object_address_window(dgp):
    best_n, best_para = None, None
    for para in dgp.paragraphs:
        m = STAGE_OBJECT_LABEL_RE.search(para)
        if not m:
            continue
        n = int(m.group(1))
        if best_n is None or n > best_n:
            best_n, best_para = n, para
    if best_para is None:
        return None
    anchor = PLAIN_ADDRESS_RE.search(best_para)
    return best_para[anchor.end():anchor.end() + 400] if anchor else None


def _bare_object_term_address_window(dgp):
    for para in dgp.paragraphs:
        if '«Объект»' not in para:
            continue
        anchor = OBJECT_TERM_ADDRESS_RE.search(para)
        return para[anchor.end():anchor.end() + 400] if anchor else None
    return None


def extract_address(dgp):
    window = _staged_object_address_window(dgp)

    if window is None:
        text = '\n'.join(dgp.paragraphs)
        anchor = ADDRESS_ANCHOR_RE.search(text)
        if anchor:
            window = text[anchor.end():anchor.end() + 400]

    if window is None:
        window = _bare_object_term_address_window(dgp)

    if window is None:
        return None

    city_match = ADDRESS_CITY_RE.search(window)
    if not city_match:
        return None

    street_match = ADDRESS_STREET_RE.search(window)
    if street_match:
        street_type = street_match.group(1)
        # Trailing punctuation belongs to the sentence, not to the street name.
        street_name = street_match.group(3).strip(' .;')
    else:
        street_match = ADDRESS_STREET_REVERSED_RE.search(window)
        if not street_match:
            return None
        street_type = street_match.group(2)
        street_name = street_match.group(1).strip(' .;,')

    city = city_match.group(1)
    address = f"г. {city}, {street_type} {street_name}"

    plot_match = ADDRESS_PLOT_RE.match(window[street_match.end():])
    return f"{address} {plot_match.group(1)}" if plot_match else address


def extract_contract_price(dgp):
    for para in dgp.paragraphs:
        m = PRICE_RE.search(para)
        if m:
            return parse_number(m.group(1))

    paragraphs = dgp.paragraphs
    for i, para in enumerate(paragraphs):
        if not SPLIT_PRICE_ANCHOR_RE.search(para):
            continue
        total = 0.0
        found_any = False
        for tail in paragraphs[i:]:
            parts = SPLIT_PRICE_PART_RE.findall(tail)
            if not parts:
                if found_any:
                    break
                continue
            for value in parts:
                number = parse_number(value)
                if number is not None:
                    total += number
                    found_any = True
        return total if found_any else None
    return None


def extract_signing_year(dgp):
    for i, para in enumerate(dgp.paragraphs):
        if PREAMBLE_CITY_RE.match(para.strip()):
            for w in dgp.paragraphs[i:i + 2]:
                m = FULL_DATE_RE.search(w) or QUOTED_DATE_RE.search(w)
                if m:
                    return m.group(1)
            break
    for para in dgp.paragraphs:
        stripped = para.strip()
        m = STANDALONE_YEAR_RE.match(stripped) or CITY_YEAR_LINE_RE.match(stripped)
        if m:
            return m.group(1)
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
        for table in doc.tables:
            for row in table:
                for cell in row:
                    result = _first_valid_class_match(cell)
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
    match = NUMERIC_CELL_RE.match(text)
    if not match:
        return None
    # Only the captured numeric portion is parsed; any trailing unit text is
    # discarded. Passing the whole cell here would let parse_number's
    # non-digit stripping append the unit's own digit to the value.
    return parse_number(match.group(1))


def _token_matches(token, text):
    if isinstance(token, tuple):
        return any(t in text for t in token)
    return token in text


def _label_matches(label, must_contain, must_not_contain):
    if not all(_token_matches(token, label) for token in must_contain):
        return False
    if any(token in label for token in must_not_contain):
        return False
    return True


def _label_end_index(row, must_contain, must_not_contain=()):
    """Index of the last cell of the label matching ``must_contain``, else None.

    The label has to fit in at most ``MAX_LABEL_CELLS`` adjacent non-numeric
    cells — Word tables sometimes split a caption over two cells, but a label
    is never spread across a whole row. Joining the entire row instead (as the
    previous implementation did) matched rows that merely happen to mention
    the tokens in unrelated columns, e.g. a "количество подземных этажей" row
    that also has a "Площадь застройки" column further right.

    Critically, must_not_contain is checked against the widest non-numeric
    window at the start position, not just the narrow window that satisfied
    must_contain. This ensures that when a label is split across cells,
    a disqualifying word in the second cell is caught. E.g. "Общая площадь"
    (satisfies must_contain) in one cell and "надземной части" (must_not_contain)
    in the adjacent cell correctly rejects the row.
    """
    for start in range(len(row)):
        # Find the first window that satisfies must_contain
        matched_end = None
        for length in range(1, MAX_LABEL_CELLS + 1):
            window = row[start:start + length]
            if len(window) < length:
                break
            if any(_numeric_cell_value(cell) is not None for cell in window):
                break
            joined = ' '.join(str(cell or '') for cell in window).lower()
            if all(_token_matches(token, joined) for token in must_contain):
                matched_end = start + length - 1
                break

        if matched_end is None:
            continue

        # Check must_not_contain against the widest non-numeric window at this start position
        for length in range(1, MAX_LABEL_CELLS + 1):
            window = row[start:start + length]
            if len(window) < length:
                break
            if any(_numeric_cell_value(cell) is not None for cell in window):
                break
            widest_window = window

        widest_joined = ' '.join(str(cell or '') for cell in widest_window).lower()
        if not any(token in widest_joined for token in must_not_contain):
            return matched_end

    return None


def _find_area_value(tables, must_contain, must_not_contain=()):
    """First number that follows a cell (or cell pair) labelled with the tokens."""
    for table in tables:
        for row in table:
            if not row:
                continue
            end = _label_end_index(row, must_contain, must_not_contain)
            if end is None:
                continue
            for cell in row[end + 1:]:
                value = _numeric_cell_value(cell)
                if value is not None:
                    return value
    return None


LINE_NUMBER_RE = re.compile(r'(?<!\w)[-+]?\d[\d\s]*(?:[.,]\d+)?(?!\w)')


def _last_number_in_line(line):
    matches = LINE_NUMBER_RE.findall(line)
    if not matches:
        return None
    return parse_number(matches[-1])


def _find_area_value_in_text(lines, must_contain, must_not_contain=()):
    """Like ``_find_area_value``, but over flat text lines (e.g. OCR output)
    instead of table rows: a label and its number don't sit in separate grid
    cells, so the number is taken from the rest of the matching line, or —
    if the label fills the whole line — from the line right after it."""
    for i, line in enumerate(lines):
        label = line.lower()
        if not _label_matches(label, must_contain, must_not_contain):
            continue
        value = _last_number_in_line(line)
        if value is not None:
            return value
        if i + 1 < len(lines):
            next_line = lines[i + 1].lower()
            # When looking ahead, also check that the next line doesn't contain
            # disqualifying words. The next line is part of the label context.
            if any(token in next_line for token in must_not_contain):
                continue
            value = _last_number_in_line(lines[i + 1])
            if value is not None:
                return value
    return None


def extract_underground_area(tz):
    return _find_area_value(
        tz.tables, ('площад', 'подземн'), must_not_contain=FOOTPRINT_EXCLUSION,
    )


def extract_aboveground_area(tz):
    return _find_area_value(
        tz.tables, ('площад', ('надземн', 'наземн')), must_not_contain=FOOTPRINT_EXCLUSION,
    )


def extract_total_area(tz):
    return _find_area_value(
        tz.tables, ('обща', 'площад'),
        must_not_contain=('подземн', 'надземн', 'наземн') + FOOTPRINT_EXCLUSION,
    )
