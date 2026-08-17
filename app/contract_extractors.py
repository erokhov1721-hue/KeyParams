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


def _months(value, label=''):
    """``"38 мес"`` — столько месяцев, сколько сказано в тексте, или None.

    Единица пишется здесь, а не берётся из документа: распознавание её калечит
    («38 мас» вместо «38 мес»), тогда как само число читается уверенно. Так в
    паспорт попадает срок, а не абзац вокруг него.

    Число опознаётся по слову про месяцы рядом с ним. Где слово написано
    прописью — «33 (тридцать три месяца)» — единицу называет сама подпись
    условия («…, мес.:»), и тогда годится первое короткое число значения.
    """
    m = TERM_MONTHS_RE.search(value)
    if m is None and MONTHS_WORD_RE.search(label):
        m = ANY_SHORT_NUMBER_RE.search(value)
    return f"{int(m.group(1))} мес" if m else None


def extract_smr_term(text):
    """The term of works in months, e.g. "38 мес".

    A clause states its own term after a colon — "1.2. Срок выполнения работ,
    мес.: 33 (тридцать три месяца)" — and that colon is what tells the two
    kinds of protocol apart, so the tail is taken and nothing else is looked
    at. Reading the line above such a clause is how a cost row from the table
    further up the page ("15. Отделка MR Base 1 256 837 680,96 Р") ended up
    glued in front of the term.

    A table row carries no colon: there OCR sometimes reorders a wrapped cell
    so the value ends up on the line *before* its label, so that one line of
    context is joined with the anchor line rather than assuming the value
    follows it.

    Either way what is wanted is the figure, and the whole point of the row is
    how many months it is. Where no figure can be made out the text goes
    through as it was read — a person can read it themselves, and a number
    nobody wrote has no business in a passport.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not SMR_ANCHOR_RE.search(line):
            continue
        tail = _clause_tail(line)
        if tail:
            return _months(tail, label=line) or tail
        window = ' '.join(l.strip() for l in lines[max(0, i - 1):i + 1] if l.strip())
        return _months(window) or window or None
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
    m = ADVANCE_RE.search(text)
    if m:
        return m.group(1).strip()

    # A protocol written as clauses rather than as a table: the wording is
    # "Авансовый платеж, % от общей стоимости работ:" with the figure on the
    # line above it.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not ADVANCE_CLAUSE_RE.search(line):
            continue
        parts = [part for part in (_line_before(lines, i), _clause_tail(line)) if part]
        if parts:
            return ' '.join(parts)
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
