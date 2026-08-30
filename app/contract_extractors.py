import re

# The protocol's terms table has one row per condition, label and value
# side by side. Whether the text comes from the PDF's own text layer or
# from OCR, a simple two-column table like this reliably comes back as
# "label ... value" on (mostly) one line, so these patterns search the
# whole joined-page text rather than parsing an actual table structure.
SMR_ANCHOR_RE = re.compile(r'срок\s+выполнения', re.IGNORECASE)

# Слово про месяцы — каким бы его ни отдало распознавание: «мес», «мес.»,
# «месяц», «месяца», а на настоящем протоколе VEER это было «мас», а подпись
# условия там же кончалась на «месяч». Между «м» и «с» допускается одна любая
# буква, поэтому «млн» и «минут» сюда не попадают: не тот срок и не те деньги.
MONTHS_WORD = r'м[а-я]?с[а-я]*\.?'
MONTHS_WORD_RE = re.compile(MONTHS_WORD, re.IGNORECASE)
# Столько месяцев: число и слово про месяцы рядом с ним. Число до трёх цифр —
# ИНН и номер строки таблицы, которые распознавание заносит в ту же строку,
# так не подхватываются.
TERM_MONTHS_RE = re.compile(rf'\b(\d{{1,3}})\s*{MONTHS_WORD}', re.IGNORECASE)
ANY_SHORT_NUMBER_RE = re.compile(r'\b(\d{1,3})\b')
ADVANCE_RE = re.compile(r'аванс\w*\s*[,;]?\s*%\s*([^\n]+)', re.IGNORECASE)
BANK_GUARANTEE_RE = re.compile(
    r'банковск\w+\s+гаранти\w+\s+на\s+возврат\s+аванса\W+([^\n]+)', re.IGNORECASE,
)
# The same two conditions as written out in a clause-by-clause protocol,
# where the grammar differs — "возврата авансового платежа" rather than "на
# возврат аванса", "Авансовый платеж, %" rather than "Аванс, %".
ADVANCE_CLAUSE_RE = re.compile(r'аванс\w*\s+платеж\w*\s*[,;]?\s*%', re.IGNORECASE)
GUARANTEE_CLAUSE_RE = re.compile(
    r'банковск\w+\s+гаранти\w+\s+возврат\w*\s+аванс\w*', re.IGNORECASE,
)
# Anchored on "bond" alone rather than on "performance bond": recognition
# mangles the long Latin word in Cyrillic surroundings — one scan turned it
# into "Реноггтлапсе" — while the short word survives intact. In a Russian
# contract protocol "bond" is distinctive enough on its own. The gap to the
# figure is bounded so that a percentage further down the page can't be
# mistaken for this one.
PERFORMANCE_BOND_RE = re.compile(r'\bbond\b.{0,200}?(\d+\s*%)', re.IGNORECASE | re.DOTALL)
BOND_ANCHOR_RE = re.compile(r'\bbond\b', re.IGNORECASE)

# Строка, которой начинается другое условие протокола: "3 Аванс, %",
# "1.4. Авансовый платеж", "5 Performance bond". Для поиска вверх это граница
# — выше неё лежит уже не то условие, что читается.
ROW_START_RE = re.compile(r'^\d+(?:[.,]\d+)*\.?\s+\S')

# Процент внутри условия. Кириллическая «З» читается как 3: в шрифтах
# протокола цифра и буква почти неразличимы, а одинокая буква перед знаком
# процента ничем иным быть не может. Дробная часть входит в захват целиком —
# иначе от «1,5 %» осталось бы «5 %».
ROW_PERCENT_RE = re.compile(r'([\dЗз]+(?:[.,]\d+)?)\s*%')

# The last stop before a value reaches the passport for smr_term/
# advance_payment — whatever produced it (a regex over the protocol text, or
# Claude reading a scanned image) might still hand back a unit word or a
# trailing clause ("30% максимальная сумма не закрытого аванса 20%" is one
# condition's sentence, not two numbers to choose between — the first one is
# the actual figure).
#
# Plain digits only — no Cyrillic «З»-as-3 correction here, unlike
# ROW_PERCENT_RE: that trick is safe only right in front of a "%" sign,
# where a lone letter truly can't be anything else. Applied to a whole
# sentence instead of one isolated token, it turns the ordinary letter «з»
# in an ordinary word — "заакрытого", "аванс за квартал" — into a stray
# digit, and a sentence is exactly what smr_term/advance_payment values are
# before this function gets at them.
BARE_NUMBER_RE = re.compile(r'(\d+(?:[.,]\d+)?)')


def bare_number(value):
    """The first number in ``value``, or None."""
    if not value:
        return None
    m = BARE_NUMBER_RE.search(value)
    return m.group(1) if m else None


def percent_value(value):
    """``bare_number(value)`` with the "%" put back on — "20%", not "20".

    The unit is dropped from every other numeric contract field (a month
    count needs no sign of its own), but a percentage without its "%" reads
    as an unfinished number rather than a whole one, so advance_payment
    keeps it — the sign, and nothing else the document said around the
    figure.
    """
    number = bare_number(value)
    return f"{number}%" if number is not None else None


def _months(value, label=''):
    """``"38"`` — how many months, as a bare number, or None.

    No unit is added: the field is only ever a count of months, so a person
    reading the passport already knows what the figure means, and a
    document-scraped word for it — «мес», «мас», «месяч» depending on what
    recognition made of the page — is exactly the kind of noise the number
    shouldn't carry.

    The number is recognized by the word about months next to it. Where the
    word is written out — «33 (тридцать три месяца)» — the clause's own
    label names the unit («…, мес.:»), and then the first short number in
    the value is the one wanted.
    """
    m = TERM_MONTHS_RE.search(value)
    if m is None and MONTHS_WORD_RE.search(label):
        m = ANY_SHORT_NUMBER_RE.search(value)
    return str(int(m.group(1))) if m else None


def extract_smr_term(text):
    """The term of works in months, as a bare number — e.g. "38".

    A clause states its own term after a colon — "1.2. Срок выполнения работ,
    мес.: 33 (тридцать три месяца)" — and that colon is what tells the two
    kinds of protocol apart, so the tail is taken and nothing else is looked
    at. Reading the line above such a clause is how a cost row from the table
    further up the page ("15. Отделка MR Base 1 256 837 680,96 Р") ended up
    glued in front of the term.

    A table row carries no colon: there OCR sometimes reorders a wrapped cell
    so the value ends up on the line *before* its label, so that one line of
    context is joined with the anchor line rather than assuming the value
    follows it. A row can just as well run the other way — the label first,
    its figure on the line under it — so the line *after* gets its own turn
    once the one before has come up empty.

    Either way what is wanted is the figure. Where no figure can be made out,
    returns None rather than the sentence around it — a person can type a
    number themselves, but a sentence where one belongs has no business in a
    passport field that's supposed to hold just that.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not SMR_ANCHOR_RE.search(line):
            continue
        tail = _clause_tail(line)
        if tail:
            return _months(tail, label=line)
        before = ' '.join(l.strip() for l in lines[max(0, i - 1):i + 1] if l.strip())
        found = _months(before)
        if found:
            return found
        after = ' '.join(l.strip() for l in lines[i:i + 2] if l.strip())
        return _months(after)
    return None


def _line_before(lines, index):
    """The nearest non-empty line above ``index``.

    Not every protocol is a table. In a written-out one the value lands on the
    line above its own clause rather than beside it — "- Авансы до 20%" sits
    over "1.4. Авансовый платеж, %...", and "нет" over the bank-guarantee
    clause. Reading the line above is what finds them.
    """
    for above in range(index - 1, max(index - 3, -1), -1):
        if lines[above].strip():
            return lines[above].strip()
    return None


def _clause_tail(line):
    """Whatever the clause says after its colon — the condition itself,
    with the numbering and the name of the clause left behind."""
    _, _, tail = line.partition(':')
    return tail.strip()


def extract_advance_payment(text):
    """The advance-payment percentage, with its sign and nothing else —
    e.g. "30%".

    A row often runs on past its own figure into an unrelated follow-up
    clause — "Аванс, % 30% максимальная сумма не закрытого аванса 20%" is
    one condition's number (30) followed by a different condition's (the cap
    on the *unclosed* advance) — so only the first number after the anchor
    is taken, not the sentence around or after it.
    """
    m = ADVANCE_RE.search(text)
    if m:
        return percent_value(m.group(1))

    # A protocol written as clauses rather than as a table: the wording is
    # "Авансовый платеж, % от общей стоимости работ:" with the figure on the
    # line above it.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not ADVANCE_CLAUSE_RE.search(line):
            continue
        parts = [part for part in (_line_before(lines, i), _clause_tail(line)) if part]
        if parts:
            return percent_value(' '.join(parts))
    return None


def _normalized_guarantee(value):
    normalized = value.strip().lower()
    # OCR routinely misreads Cyrillic "Не" as Latin "He" — the Н/H and
    # е/e glyphs are visually identical in most fonts.
    if normalized.startswith(('не включ', 'he включ', 'нет', 'het')):
        return 'Не включено'
    if normalized.startswith(('включ', 'да')):
        return 'Включено'
    return value.strip()


def extract_bank_guarantee(text):
    m = BANK_GUARANTEE_RE.search(text)
    if m:
        return _normalized_guarantee(m.group(1))

    # Written out as a clause instead of a table row: "Банковская гарантия
    # возврата авансового платежа:" with the answer on the line above.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not GUARANTEE_CLAUSE_RE.search(line):
            continue
        above = _line_before(lines, i)
        if above:
            return _normalized_guarantee(above)
    return None


def _bond_percent_in_row(lines, index):
    """The percentage belonging to the bond condition itself, or None.

    A protocol laid out as a two-column table wraps the value cell over two
    visual lines, and OCR puts the first of them *above* the label while
    leaving the tail glued to it: "Банковская исполнения З %" / "гарантия —
    от" / "1.8. Performance bond: цены работ." So the label's own line is
    read first, then the lines above it — the pieces of the same cell.

    The walk upwards stops at a line that starts another condition of the
    protocol. Without that the "30%" of "3 Аванс, %" two rows up would be
    taken for the bond, and it is not the bond's figure.
    """
    for line in _bond_row_lines(lines, index):
        m = ROW_PERCENT_RE.search(line)
        if m:
            return m.group(1).replace('З', '3').replace('з', '3') + '%'
    return None


def _bond_row_lines(lines, index):
    """The label's line first, then the wrapped pieces above it, nearest up."""
    yield lines[index]
    for above in range(index - 1, max(index - 4, -1), -1):
        line = lines[above].strip()
        if not line or ROW_START_RE.match(line):
            return
        yield line


def extract_performance_bond(text):
    """The performance-bond percentage, e.g. "3%".

    Reads the condition's own row where it has a figure of its own. Only
    where it hasn't does the search widen to the text that follows — a
    protocol whose bond cell comes back empty from OCR still says the figure
    a line or two further down, under the retention clause.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if BOND_ANCHOR_RE.search(line):
            found = _bond_percent_in_row(lines, i)
            if found:
                return found
            break

    m = PERFORMANCE_BOND_RE.search(text)
    return m.group(1).replace(' ', '') if m else None
