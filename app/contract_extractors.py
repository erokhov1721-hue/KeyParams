import re

# The protocol's terms table has one row per condition, label and value
# side by side. Whether the text comes from the PDF's own text layer or
# from OCR, a simple two-column table like this reliably comes back as
# "label ... value" on (mostly) one line, so these patterns search the
# whole joined-page text rather than parsing an actual table structure.
SMR_ANCHOR_RE = re.compile(r'срок\s+выполнения', re.IGNORECASE)
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


def extract_smr_term(text):
    """The SMR-term row's value, e.g. "30 месяца, с даты передачи ...".

    OCR sometimes reorders a wrapped cell so the value ends up on the line
    *before* its label, so this joins that one line of context with the
    anchor line rather than assuming the value follows it — a rougher
    capture, but the "Найдено в протоколе — проверьте" badge already tells
    the user to check it.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if SMR_ANCHOR_RE.search(line):
            window = ' '.join(l.strip() for l in lines[max(0, i - 1):i + 1] if l.strip())
            return window or None
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


def extract_performance_bond(text):
    m = PERFORMANCE_BOND_RE.search(text)
    return m.group(1).replace(' ', '') if m else None
