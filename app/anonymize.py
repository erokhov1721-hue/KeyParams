import re

from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter

# 10 or 12 digits right after "ИНН" (with or without a separator), not
# followed by another digit — so a 12-digit ИНН isn't cut short by the
# 10-digit alternative matching just its first 10 digits.
_INN_RE = re.compile(r'ИНН[:\s]*(\d{12}|\d{10})(?!\d)', re.IGNORECASE)

_TYPE_PREFIX = {"PER": "PERSON", "ORG": "ORGANIZATION"}

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
    pieces = []
    cursor = 0
    for start, stop, prefix, original in spans:
        if start < cursor:
            continue  # overlaps a span already emitted — skip rather than double-count
        key = (prefix, original.lower())
        token = token_by_mention.get(key)
        if token is None:
            counters[prefix] += 1
            token = f"<{prefix}_{counters[prefix]}>"
            token_by_mention[key] = token
            token_map[token] = original
        pieces.append(text[cursor:start])
        pieces.append(token)
        cursor = stop
    pieces.append(text[cursor:])
    return "".join(pieces), token_map


def deanonymize_value(value, token_map: dict):
    """If ``value`` is a string that exactly matches a token, return the
    original text it stood for; otherwise return ``value`` unchanged."""
    if isinstance(value, str) and value in token_map:
        return token_map[value]
    return value
