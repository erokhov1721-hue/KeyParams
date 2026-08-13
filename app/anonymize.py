import re

from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter

# 10 or 12 digits right after "ИНН" (with or without a separator), not
# followed by another digit — so a 12-digit ИНН isn't cut short by the
# 10-digit alternative matching just its first 10 digits.
_INN_RE = re.compile(r'ИНН[:\s]*(\d{12}|\d{10})(?!\d)', re.IGNORECASE)

_TYPE_PREFIX = {"PER": "PERSON", "ORG": "ORGANIZATION"}

# Matches a quoted name, e.g. «Ромашка» or "Ромашка". Used by the backstop
# sweep below to catch the same organization name recurring under a
# different legal-form prefix — Natasha's NER span for "ООО «Ромашка»"
# doesn't literally occur inside "Общество с ограниченной
# ответственностью «Ромашка»", but the quoted core name «Ромашка» does.
_QUOTED_RE = re.compile(r'[«"]([^»"]+)[»"]')


def _sweep_pattern(original):
    match = _QUOTED_RE.search(original)
    if match:
        return match.group(0)
    return original

_segmenter = None
_ner_tagger = None


def _get_natasha():
    global _segmenter, _ner_tagger
    if _segmenter is None:
        embedding = NewsEmbedding()
        _segmenter = Segmenter()
        _ner_tagger = NewsNERTagger(embedding)
    return _segmenter, _ner_tagger


def anonymize_text(text: str):
    """Replace every organization, person, and ИНН mention in ``text`` with
    a token — ``<ORGANIZATION_N>``, ``<PERSON_N>``, ``<INN_N>`` — numbered
    within its own category in the order it's first mentioned. The same
    mention (matched case-insensitively) always gets the same token.

    After the NER/regex pass, a literal case-insensitive sweep folds in any
    OTHER occurrence of an already-tokenized PERSON/ORGANIZATION substring
    that Natasha's tagger missed — this is what catches the extremely
    common Russian contract pattern "Общество с ограниченной
    ответственностью «Ромашка» (ООО «Ромашка»)", where Natasha tags only
    the parenthetical short form and would otherwise leave the identical
    name in the spelled-out legal form reaching Claude in plaintext.

    Returns ``(anonymized_text, token_map)`` where ``token_map`` maps each
    token back to the original substring it replaced.
    """
    segmenter, ner_tagger = _get_natasha()
    doc = Doc(text)
    doc.segment(segmenter)
    doc.tag_ner(ner_tagger)

    spans = []
    for span in doc.spans:
        prefix = _TYPE_PREFIX.get(span.type)
        if prefix is None:
            continue
        spans.append((span.start, span.stop, prefix, span.text))
    for match in _INN_RE.finditer(text):
        spans.append((match.start(1), match.end(1), "INN", match.group(1)))
    spans.sort(key=lambda s: s[0])

    token_map = {}
    token_by_mention = {}
    counters = {"PERSON": 0, "ORGANIZATION": 0, "INN": 0}

    def _token_for(prefix, original):
        key = (prefix, original.lower())
        token = token_by_mention.get(key)
        if token is None:
            counters[prefix] += 1
            token = f"<{prefix}_{counters[prefix]}>"
            token_by_mention[key] = token
            token_map[token] = original
        return token

    resolved = [(start, stop, _token_for(prefix, original)) for start, stop, prefix, original in spans]

    # Backstop sweep: fold in every other literal occurrence of an
    # already-tokenized PERSON/ORGANIZATION mention that NER missed.
    seen_mentions = {
        (prefix, original.lower())
        for _, _, prefix, original in spans
        if prefix in ("PERSON", "ORGANIZATION")
    }
    covered = {(start, stop) for start, stop, _ in resolved}
    for prefix, lowered in seen_mentions:
        token = token_by_mention[(prefix, lowered)]
        original = token_map[token]
        pattern = _sweep_pattern(original)
        for match in re.finditer(re.escape(pattern), text, re.IGNORECASE):
            span_key = (match.start(), match.end())
            if span_key in covered:
                continue
            covered.add(span_key)
            resolved.append((match.start(), match.end(), token))

    resolved.sort(key=lambda r: r[0])

    pieces = []
    cursor = 0
    for start, stop, token in resolved:
        if start < cursor:
            continue  # overlaps a span already emitted — skip rather than double-count
        pieces.append(text[cursor:start])
        pieces.append(token)
        cursor = stop
    pieces.append(text[cursor:])
    return "".join(pieces), token_map


_TOKEN_RE = re.compile(r'<(?:ORGANIZATION|PERSON|INN)_\d+>')


def deanonymize_value(value, token_map: dict):
    """If ``value`` is a string that exactly matches a token, return the
    original text it stood for. If a token appears embedded inside a larger
    string (e.g. Claude echoed surrounding context around it), substitute
    every token occurrence in place. Otherwise return ``value`` unchanged."""
    if not isinstance(value, str):
        return value
    if value in token_map:
        return token_map[value]
    if _TOKEN_RE.search(value):
        return _TOKEN_RE.sub(lambda m: token_map.get(m.group(0), m.group(0)), value)
    return value
