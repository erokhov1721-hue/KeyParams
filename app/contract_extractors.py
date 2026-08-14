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
PERFORMANCE_BOND_RE = re.compile(r'performance\s+bond\b.*?(\d+\s*%)', re.IGNORECASE | re.DOTALL)


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


def extract_advance_payment(text):
    m = ADVANCE_RE.search(text)
    return m.group(1).strip() if m else None


def extract_bank_guarantee(text):
    m = BANK_GUARANTEE_RE.search(text)
    if not m:
        return None
    normalized = m.group(1).strip().lower()
    # OCR routinely misreads Cyrillic "Не" as Latin "He" — the Н/H and
    # е/e glyphs are visually identical in most fonts.
    if normalized.startswith(('не включ', 'he включ')):
        return 'Не включено'
    if normalized.startswith('включ'):
        return 'Включено'
    return m.group(1).strip()


def extract_performance_bond(text):
    m = PERFORMANCE_BOND_RE.search(text)
    return m.group(1).replace(' ', '') if m else None
