"""Putting the cost of different objects on one scale.

Two objects priced four years apart, one of them under a different rate of
VAT, cannot be compared by their figures alone: the difference would be
mostly about when the contract was signed. This brings them together — but
only when asked. Left alone it changes nothing, because the first question
anyone has of a project is what it cost, not what it would have cost in
today's money.
"""

import re
from dataclasses import dataclass
from datetime import date

from . import cost_increase, estimate_sections, extractors, passport as passport_module
from . import project_filter
from .passport import format_number

# The three ways to look at money across projects signed under different
# VAT rates — spelled out as named modes rather than left as "a rate, or
# None" for the page to puzzle out, because the third mode ("own") and the
# first ("net", a target of exactly 0%) would otherwise both have to be
# read off the same falsy-vs-None distinction a stray bug could erase.
VAT_MODE_OWN = "own"
VAT_MODE_NET = "net"
VAT_MODE_CUSTOM = "custom"

DEFAULT_VAT_RATE = 22.0
DEFAULT_INFLATION = 12.0
# The year money gets brought to when no other year is chosen — today's, not
# a number that goes stale the moment the calendar turns.
DEFAULT_TARGET_YEAR = date.today().year

NOTE_NO_ESTIMATE = "смета не загружена"
NOTE_NO_AREA = "рубли, не ₽/м²: общая площадь неизвестна"
NOTE_NO_VAT = "без поправки на НДС: ставка неизвестна"
NOTE_NO_YEAR = "без поправки на инфляцию: год подписания неизвестен"
NOTE_NO_INCREASE = "без файла удорожания"
NOTE_NO_VIS_OVERRUN = "нет данных ВИС для этого проекта"

# The claims registry (app.vis_reestr) only ever forecasts an
# engineering-systems ("ВИС") overrun — there's no column in it naming any
# other section — so that's the only section its money can extend.
VIS_OVERRUN_SECTION_KEY = "utilities"

_YEAR_RE = re.compile(r"(19|20)\d{2}")


@dataclass(frozen=True)
class Adjustments:
    """What to bring the figures to. ``None`` means "leave them alone"."""

    vat_rate: float = None
    inflation: float = None
    target_year: int = DEFAULT_TARGET_YEAR

    @property
    def applied(self) -> bool:
        return self.vat_rate is not None or self.inflation is not None

    @property
    def vat_mode(self) -> str:
        """Which of the three scenarios this is — for the form to show the
        right radio checked. The maths itself never asks this question, only
        ``vat_rate``: ``None`` acts on nothing, any number (0 included) is a
        target every project gets carried to."""
        if self.vat_rate is None:
            return VAT_MODE_OWN
        if self.vat_rate == 0.0:
            return VAT_MODE_NET
        return VAT_MODE_CUSTOM

    @property
    def vat_display(self) -> str:
        """What to put in the field — the chosen rate, or the default when the
        correction is off, so switching it on doesn't start from an empty box."""
        return _percent_text(
            self.vat_rate if self.vat_rate is not None else DEFAULT_VAT_RATE
        )

    @property
    def inflation_display(self) -> str:
        return _percent_text(
            self.inflation if self.inflation is not None else DEFAULT_INFLATION
        )


def _percent_text(value) -> str:
    return f"{value:g}".replace(".", ",")


def parse_percent(text):
    """A percentage written any of the ways a person writes one."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    if text is None:
        return None
    return extractors.parse_number(str(text).replace("%", " "))


def parse_year(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        year = int(value)
        return year if 1900 <= year <= 2100 else None
    match = _YEAR_RE.search(str(value or ""))
    return int(match.group()) if match else None


# A VAT rate outside this range isn't a tax rate a person meant to type —
# it's a stray digit or an adversarial query string — and would otherwise
# sit in ``project_factor``'s numerator undisturbed.
VAT_RATE_RANGE = (0.0, 100.0)

# An inflation rate outside this range compounds, over decades, into a
# number a 64-bit float can't hold — ``(1 + rate/100) ** years`` overflows
# for an old enough signing year long before the rate itself looks absurd.
# The floor sits above -100%: at exactly -100% the base of that power goes
# to zero, and every year past the target collapses the multiplier to it.
INFLATION_RANGE = (-99.0, 500.0)


def _percent_in_range(text, low, high):
    """The figure, or None if it can't be read or doesn't land in
    ``[low, high]`` — out of range is treated exactly like unreadable: both
    are "not a usable answer to this question", not "a value to act on"."""
    value = parse_percent(text)
    if value is None or not (low <= value <= high):
        return None
    return value


def adjustments_from_args(args) -> Adjustments:
    """Read the settings off the page's own address.

    VAT reads as one of three named modes (``vat_mode`` — see
    ``VAT_MODE_OWN``/``VAT_MODE_NET``/``VAT_MODE_CUSTOM``) rather than a
    checkbox next to a figure: the three read as genuinely different
    questions ("what did it actually cost", "what would it cost with no tax
    at all", "what would it cost at one rate everyone shares") and a single
    on/off switch left the middle one reachable only by typing 0 into a box
    that looked like it was asking for the third. Missing or unrecognised
    text here — someone editing the address bar by hand — falls back to
    "own", the same as never having asked at all.

    Inflation keeps its own switch (``inflation_on``): an unticked checkbox
    submits nothing at all, which is exactly the behaviour wanted, and it
    keeps zero per cent — "bring these to one year, and tell me which ones
    have no year" — distinguishable from no correction at all.

    A switch or mode that's on with an unreadable figure beside it — or one
    outside a sane range for what it claims to be — falls back to the
    default rather than silently doing nothing, or worse, feeding the maths
    a number it can't survive.
    """
    vat_mode = args.get("vat_mode")
    if vat_mode == VAT_MODE_NET:
        vat = 0.0
    elif vat_mode == VAT_MODE_CUSTOM:
        vat = _percent_in_range(args.get("vat"), *VAT_RATE_RANGE)
        if vat is None:
            vat = DEFAULT_VAT_RATE
    else:
        vat = None

    inflation = None
    if args.get("inflation_on"):
        inflation = _percent_in_range(args.get("inflation"), *INFLATION_RANGE)
        if inflation is None:
            inflation = DEFAULT_INFLATION

    year = parse_year(args.get("year")) or DEFAULT_TARGET_YEAR
    return Adjustments(vat_rate=vat, inflation=inflation, target_year=year)


# Условия договора — те же пять, что стоят в паспорте договора на странице
# проекта, и в том же порядке. Список берётся оттуда, а не пишется здесь
# заново, чтобы новое условие появлялось в сравнении само.
TERMS_FIELDS = passport_module.CONTRACT_FIELDS

TERMS_EMPTY = "—"


def build_terms_table(slugs, passports):
    """Условия договора по проектам, или None, когда их ни у кого нет.

    Одна и та же таблица идёт и на страницу, и в PDF: собирается здесь, чтобы
    разойтись они не могли.

    Строки — постоянный список из пяти условий: прочерк напротив проекта
    сообщает, что этого условия у него не нашлось, и это тоже ответ. А вот
    таблица целиком из прочерков не сообщает ничего — там, где ни у одного
    проекта протокол не прочитан, её нет вовсе.
    """
    rows = []
    for field in TERMS_FIELDS:
        # Клетки лежат под именем cells, а не values: у словаря есть метод
        # values(), и шаблон взял бы метод вместо данных.
        cells = []
        for slug in slugs:
            value = passports[slug].get(field)
            text = str(value).strip() if value is not None else ""
            cells.append(text or TERMS_EMPTY)
        rows.append({
            "field": field,
            "label": passport_module.CONTRACT_FIELD_LABELS.get(field, field),
            "cells": cells,
        })

    if all(cell == TERMS_EMPTY for row in rows for cell in row["cells"]):
        return None
    return {"rows": rows}


def project_factor(vat, year_signed, adjustments):
    """``(multiplier, notes)`` for one project's figures.

    One multiplier serves the whole column: both corrections are a constant
    per project, so the order they are applied in doesn't matter and a
    section's share of the total is left untouched.
    """
    factor = 1.0
    notes = []

    if adjustments.vat_rate is not None:
        source = parse_percent(vat)
        # A rate at or below -100% would zero or flip the sign of this
        # divisor — not a real VAT rate, so treated the same as an unread
        # one rather than handed to the division.
        if source is None or source <= -100.0:
            notes.append(NOTE_NO_VAT)
        else:
            factor *= (100.0 + adjustments.vat_rate) / (100.0 + source)

    if adjustments.inflation is not None:
        year = parse_year(year_signed)
        if year is None:
            notes.append(NOTE_NO_YEAR)
        else:
            factor *= (1.0 + adjustments.inflation / 100.0) ** (
                adjustments.target_year - year
            )

    return factor, notes


def _money(value):
    return format_number(round(value)) if value is not None else None


def _as_float_costs(costs_by_slug):
    """``costs_by_slug`` (``Decimal`` money, straight from
    ``estimate_sections``/``excel_report.estimate_costs``) converted to
    plain ``float``.

    Everything this module does with a cost from here on is a ratio or a
    derived display value already — a VAT/inflation factor, a ₽/м² rate, a
    deviation from another project's figure, a share of a total — never a
    sum across many estimate lines that would compound a float's rounding
    the way the review flagged. That summation already happened upstream,
    in Decimal, where the many terms actually are; converting once at the
    door here keeps the rest of this module's arithmetic exactly what it
    was before Decimal existed anywhere in this codebase.
    """
    return {
        slug: {key: float(value) for key, value in costs.items()}
        for slug, costs in (costs_by_slug or {}).items()
    }


def _source_vat(passport):
    """The rate the estimate was priced at.

    The passport's own ``vat`` field wins when it's set: the project page,
    the PDF and every export already show that value, and deriving a
    second, different rate from the signing year here — the year-by-year
    rule this project used to prefer — meant a project with an uploaded
    protocol could show one VAT rate everywhere else and a different one
    on this page, with nothing to explain why. Falls back to the rule by
    year only when there's no stored rate to read yet: that's every
    project before a contract-terms protocol has been uploaded, and the
    rule is what keeps the correction from going inert on all of them.

    A year edited later does not retroactively update an already-stored
    rate — by design: the stored rate may be what the protocol actually
    says, not a guess from the rule, and silently overwriting it on every
    unrelated year correction would be its own way of losing information.
    """
    stored = passport.get("vat")
    if stored:
        return stored
    return passport_module.vat_for_year(parse_year(passport.get("year_signed")))


def _column(slug, passport, costs, adjustments, extra_notes=()):
    factor, notes = project_factor(
        _source_vat(passport), passport.get("year_signed"), adjustments,
    )
    area = passport.get("total_area_sqm")
    if not costs:
        notes.insert(0, NOTE_NO_ESTIMATE)
    elif not area:
        notes.insert(0, NOTE_NO_AREA)
    notes.extend(note for note in extra_notes if note)
    return {
        "slug": slug,
        "name": passport.get("project_name") or slug,
        "factor": factor,
        "area": area if area else None,
        "has_estimate": bool(costs),
        "per_sqm": bool(costs and area),
        "notes": notes,
    }


def _cell(column, costs, key):
    """One project's figure for one section.

    Empty is not zero here: a section the estimate doesn't carry has no
    figure, while a section it carries at nought really did cost nothing.
    """
    amount = costs.get(key)
    if amount is None:
        return {"value": None, "display": "—", "deviation": None, "deviation_display": ""}
    value = amount * column["factor"]
    if column["per_sqm"]:
        value = value / column["area"]
    return {"value": value, "display": _money(value), "deviation": None,
            "deviation_display": ""}


# Шкала отклонения для заливки тепловой карты, ±%. Одна на всю таблицу: если
# у каждой строки она своя, ячейки перестают сравниваться между собой и
# смысл теряется.
DEVIATION_SCALE = 50.0

# Ниже этой доли раздел приглушается. «Гидроизоляция» даёт +90%, но в деньгах
# это 503 ₽/м² при итоге 139 000 — ярко-красный процент там поднимает тревогу
# на ровном месте.
MINOR_SHARE = 1.0


# Прозрачность заливки ячейки в тепловом виде таблицы разделов. Нижняя
# граница не нулевая: у отклонения около 0% заливка должна читаться «почти
# прозрачной», а не полностью исчезать — иначе ячейка без заливки не
# отличается от «нет данных». Верхняя — не 100%: сплошная заливка сделала бы
# число под ней нечитаемым.
HEAT_MIN_MIX = 8.0
HEAT_MAX_MIX = 40.0


def _add_heat(cell):
    """Заливка ячейки по силе отклонения — тепловая карта таблицы разделов.

    ``color-mix()`` смешивает готовый цвет с прозрачностью вместо
    захардкоженного rgba, но токен для перерасхода и токен для экономии
    выбраны по разным причинам:

    - перерасход — ``--red``: «дороже» само по себе везде в этом
      приложении читается этим красным, менять тут нечего.
    - экономия — свой собственный ``--heat-savings``, а не ``--accent``.
      ``--accent`` в этой таблице до сих пор случайно совпадал с «дешевле»
      только потому, что так исторически сложилось у бара; но в теме
      «Опал» и вообще как акцентный цвет темы он означает «главное
      действие», а не «дешевле», и в других темах бывает бирюзовым или
      фиолетовым — цвет заливки перестаёт однозначно читаться как «синее
      дешевле». ``--heat-savings`` — свой фиксированный синий (см. :root),
      привязанный только к этой таблице, не к общей семантике «лучше».

    ``heat_mix`` хранит ту же силу заливки числом (0–100) рядом с готовой
    CSS-строкой: PDF рисует ту же плашку через reportlab, где `color-mix()`
    не распарсить, и берёт готовое число вместо того, чтобы пересчитывать
    формулу второй раз в другом файле.
    """
    deviation = cell["deviation"]
    if deviation is None:
        cell["heat_bg"] = None
        cell["heat_mix"] = None
        return
    magnitude = abs(deviation) * 100
    mix = HEAT_MIN_MIX + min(1.0, magnitude / DEVIATION_SCALE) * (HEAT_MAX_MIX - HEAT_MIN_MIX)
    token = "--red" if deviation > 0 else "--heat-savings"
    cell["heat_bg"] = f"color-mix(in srgb, var({token}) {mix:.1f}%, transparent)"
    cell["heat_mix"] = mix


def _add_deviations(cells):
    """How each project stands against the first one chosen.

    Against the first rather than against the cheapest: the first column is
    the one being asked about, and the rest are the yardstick.
    """
    base = cells[0]["value"] if cells else None
    if base:
        for cell in cells[1:]:
            if cell["value"] is None:
                continue
            cell["deviation"] = cell["value"] / base - 1.0
            cell["deviation_display"] = (
                f"{cell['deviation'] * 100:+.0f}%".replace("-", "−")
            )
    for cell in cells:
        _add_heat(cell)


def _apply_increase(slugs, costs_by_slug, reports):
    """``costs_by_slug`` with every section swapped for its cost-increase
    figure — the workbook's "стало" where a section was restated, the
    estimate's own figure everywhere else — so "with additional works"
    means exactly the same thing here as it does on the удорожание block.

    A project with no cost-increase file keeps its estimate figures as they
    are (there is nothing to add them to) and gets ``NOTE_NO_INCREASE`` so
    the unchanged number isn't mistaken for "no additional works happened".
    """
    reports = reports or {}
    merged = dict(costs_by_slug)
    notes = {}
    for slug in slugs:
        costs = costs_by_slug.get(slug)
        report = reports.get(slug)
        if report is None:
            if costs:
                notes[slug] = NOTE_NO_INCREASE
            continue
        merged[slug] = {
            **(costs or {}), **{row.key: float(row.current) for row in report.rows},
        }
    return merged, notes


_NAME_TOKEN_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)


def _name_tokens(text):
    """A name's words, lowercased — for matching against the VIS registry's
    own free-text "объект" field.

    A KeyParams project name usually carries more than the registry's own,
    shorter name for the same object — "Тушино 1 Cityzen" here against
    "Тушино 1" there — so an exact string match missed it. Matched as
    whole words rather than a raw substring too: "Тушино 1" is a substring
    of "Тушино 12" as bare characters, and would wrongly match a different
    building the same way.
    """
    return {t.lower() for t in _NAME_TOKEN_RE.findall(str(text or ""))}


def vis_overrun_by_slug(slugs, passports, price_increase_rows):
    """``{slug: Decimal}`` — each project's VIS claims-registry
    cost-overrun forecast (``app.vis_reestr.build_analytics``'s
    ``price_increase``), matched to a project by its name against the
    registry's "объект" column.

    A match is made whenever one name's words are entirely contained in the
    other's, in either direction — not merely overlapping: money is at
    stake, and a match on a single shared word risks crediting one
    project's overrun to an unrelated one that just happens to share it
    ("Тушино 1" and "Мира Тушино" share "тушино" but name different
    objects; neither one's words fully contain the other's). A project the
    registry names nothing for is simply absent from the result, same as
    one with no estimate at all.
    """
    registry = [
        (_name_tokens(row["name"]), row["sum"])
        for row in price_increase_rows
    ]
    result = {}
    for slug in slugs:
        project_tokens = _name_tokens(passports[slug].get("project_name"))
        if not project_tokens:
            continue
        for vis_tokens, overrun in registry:
            if vis_tokens and (vis_tokens <= project_tokens or project_tokens <= vis_tokens):
                result[slug] = overrun
                break
    return result


def _apply_vis_overrun(slugs, costs_by_slug, vis_overrun_by_slug):
    """``costs_by_slug`` with each project's VIS cost-overrun forecast (see
    ``vis_overrun_by_slug`` above) added onto its "Инженерные системы"
    figure.

    A project the registry has no matching object for keeps its section
    figures as they are and gets ``NOTE_NO_VIS_OVERRUN``, the same way a
    project with no cost-increase file is noted under ``_apply_increase``
    rather than left looking untouched by coincidence.
    """
    vis_overrun_by_slug = vis_overrun_by_slug or {}
    merged = dict(costs_by_slug)
    notes = {}
    for slug in slugs:
        costs = costs_by_slug.get(slug)
        overrun = vis_overrun_by_slug.get(slug)
        if overrun is None:
            if costs:
                notes[slug] = NOTE_NO_VIS_OVERRUN
            continue
        costs = dict(costs or {})
        costs[VIS_OVERRUN_SECTION_KEY] = costs.get(VIS_OVERRUN_SECTION_KEY, 0.0) + float(overrun)
        merged[slug] = costs
    return merged, notes


def build_section_table(
    slugs, passports, costs_by_slug, adjustments, reports=None, use_increase=False,
    vis_overrun_by_slug=None, use_vis_overrun=False,
):
    """The section-by-section comparison, or None when there is nothing to show.

    Returns None if not one of the chosen projects has an estimate: a table of
    nothing but dashes only takes up the screen.

    ``use_increase`` swaps each project's estimate figures for its
    cost-increase workbook's current ones (see ``_apply_increase``) — the
    same underlying figures the удорожание block already computes from
    ``reports``, just folded into this table instead of shown apart from it.

    ``use_vis_overrun`` adds each project's VIS claims-registry cost-overrun
    forecast onto its "Инженерные системы" figure (see ``_apply_vis_overrun``)
    — independent of ``use_increase``: on top of the swapped "стало" figure
    where both are on, on top of the plain estimate where only this one is.
    """
    costs_by_slug = _as_float_costs(costs_by_slug)
    increase_notes = {}
    if use_increase:
        costs_by_slug, increase_notes = _apply_increase(slugs, costs_by_slug, reports)
    vis_notes = {}
    if use_vis_overrun:
        costs_by_slug, vis_notes = _apply_vis_overrun(slugs, costs_by_slug, vis_overrun_by_slug)
    if not any(costs_by_slug.get(slug) for slug in slugs):
        return None

    columns = [
        _column(
            slug, passports[slug], costs_by_slug.get(slug) or {}, adjustments,
            extra_notes=(increase_notes.get(slug), vis_notes.get(slug)),
        )
        for slug in slugs
    ]

    rows = []
    for key in estimate_sections.CATEGORY_KEYS:
        cells = [_cell(column, costs_by_slug.get(column["slug"]) or {}, key)
                 for column in columns]
        if all(cell["value"] is None for cell in cells):
            # A section none of the estimates carries is a row of dashes, and
            # seventeen rows is already a lot to read.
            continue
        _add_deviations(cells)
        rows.append({
            "key": key,
            "label": estimate_sections.CATEGORY_LABELS[key],
            "cells": cells,
        })

    total = []
    for column in columns:
        costs = costs_by_slug.get(column["slug"]) or {}
        if not costs:
            total.append({"value": None, "display": "—", "deviation": None,
                          "deviation_display": ""})
            continue
        value = sum(costs.values()) * column["factor"]
        if column["per_sqm"]:
            value = value / column["area"]
        total.append({"value": value, "display": _money(value), "deviation": None,
                      "deviation_display": ""})
    _add_deviations(total)
    # По убыванию доли, а не в порядке из сметы: первым идёт то, из чего
    # стоимость в основном и складывается. Итоговая строка живёт отдельно и
    # в сортировке не участвует — она всегда последняя.
    rows.sort(
        key=lambda row: (
            row["cells"][0]["value"] if row["cells"][0]["value"] is not None else -1.0
        ),
        reverse=True,
    )
    _add_weights(rows, total[0]["value"] if total else None)
    return {
        "columns": columns,
        "rows": rows,
        "total": {"label": "Итого СМР", "cells": total},
        "adjustments": adjustments,
        "use_increase": use_increase,
        "use_vis_overrun": use_vis_overrun,
    }


UNIT_MONEY = "money"
UNIT_PER_SQM = "per_sqm"
UNIT_AREA = "area"

# What the two cards put side by side. Money is corrected for VAT and
# inflation like everything else on the page; areas are not — a square metre
# in 2020 is a square metre in 2026.
PAIR_METRICS = [
    ("contract_price", "Цена работ по договору", UNIT_MONEY),
    ("contract_per_sqm", "Цена работ на 1 м²", UNIT_PER_SQM),
    ("total_area", "Общая площадь комплекса", UNIT_AREA),
    ("underground_area", "Площадь подземной части", UNIT_AREA),
    ("aboveground_area", "Площадь надземной части", UNIT_AREA),
    ("estimate_total", "Итого СМР по смете", UNIT_MONEY),
    ("estimate_per_sqm", "Итого СМР на 1 м²", UNIT_PER_SQM),
]


def _format_metric(value, unit):
    if value is None:
        return "—"
    if unit == UNIT_MONEY:
        # Полным числом, а не в миллионах: цену договора и итог сметы сверяют
        # с самими документами, а «18 364 млн ₽» прячет ровно те знаки, по
        # которым сверяют. Копейки — до целых рублей: на десяти знаках они
        # ничего не решают, как и десятая метра на площади ниже.
        return f"{format_number(round(value))} ₽"
    if unit == UNIT_PER_SQM:
        return f"{format_number(round(value))} ₽/м²"
    # Whole square metres: a tenth of a metre on a building of a hundred
    # thousand is noise, and "131 940.40 м²" reads worse than the figure is
    # worth.
    return f"{format_number(round(value))} м²"


def _signed(value, unit):
    if value is None:
        return ""
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{_format_metric(abs(value), unit)}"


def _metric_values(passport, costs, factor):
    """Every figure the cards can show, for one project."""
    area = passport.get("total_area_sqm") or None
    price = passport.get("contract_price_rub")
    price = price * factor if price is not None else None
    estimate = sum(costs.values()) * factor if costs else None
    return {
        "contract_price": price,
        "contract_per_sqm": price / area if price is not None and area else None,
        "total_area": area,
        "underground_area": passport.get("underground_area_sqm"),
        "aboveground_area": passport.get("aboveground_area_sqm"),
        "estimate_total": estimate,
        "estimate_per_sqm": estimate / area if estimate is not None and area else None,
    }


def build_pair_cards(left, right, passports, costs_by_slug, adjustments):
    """Two objects head to head, or None when there aren't two to compare.

    The difference is read left to right — how the right-hand object stands
    against the left-hand one — because that is the order they are chosen in.
    Money is coloured (dearer is red), area is not: a bigger building is
    neither better nor worse.
    """
    if not left or not right or left == right:
        return None
    if left not in passports or right not in passports:
        return None

    costs_by_slug = _as_float_costs(costs_by_slug)
    sides = []
    for slug in (left, right):
        passport = passports[slug]
        factor, notes = project_factor(
            _source_vat(passport), passport.get("year_signed"), adjustments,
        )
        costs = costs_by_slug.get(slug) or {}
        sides.append({
            "slug": slug,
            "name": passport.get("project_name") or slug,
            "notes": notes,
            "values": _metric_values(passport, costs, factor),
            "costs": {key: value * factor for key, value in costs.items()},
            "area": passport.get("total_area_sqm") or None,
        })

    metrics = []
    for key, label, unit in PAIR_METRICS:
        a, b = sides[0]["values"][key], sides[1]["values"][key]
        metrics.append({
            "label": label,
            "unit": unit,
            "left": _format_metric(a, unit),
            "right": _format_metric(b, unit),
            "delta_display": _percent_change(a, b),
            "diff_display": _signed(b - a, unit) if a is not None and b is not None else "",
            "dearer": None if a is None or b is None or unit == UNIT_AREA else b > a,
        })

    sections = _section_deltas(sides)
    # Для строки «Итого» в waterfall-виде того же блока — тем же _signed,
    # что и у каждой строки выше, чтобы формат (знак, пробел-разделитель,
    # единица) не разъехался между строкой и итогом. Сама sections не
    # трогается: это отдельное поле, бары-вид его не читает.
    sections_per_sqm = bool(sides[0]["area"] and sides[1]["area"])
    sections_total_display = _signed(
        sum(row["difference"] for row in sections),
        UNIT_PER_SQM if sections_per_sqm else UNIT_MONEY,
    ) if sections else ""

    return {
        "left": sides[0],
        "right": sides[1],
        "metrics": metrics,
        "sections": sections,
        "sections_total_display": sections_total_display,
    }


def _percent_change(before, after):
    if before is None or after is None or not before:
        return ""
    change = after / before - 1.0
    return f"{change * 100:+.1f} %".replace("-", "−").replace(".", ",")


def _section_deltas(sides):
    """Where the right-hand object's money goes that the left-hand one's does
    not, section by section, biggest difference first.

    Compared per square metre wherever both objects have an area — two
    buildings of different size have little to say to each other in roubles.
    """
    per_sqm = bool(sides[0]["area"] and sides[1]["area"])

    rows = []
    for key in estimate_sections.CATEGORY_KEYS:
        values = []
        for side in sides:
            value = side["costs"].get(key)
            if value is not None and per_sqm:
                value = value / side["area"]
            values.append(value)
        if values[0] is None and values[1] is None:
            continue
        difference = (values[1] or 0.0) - (values[0] or 0.0)
        rows.append({
            "key": key,
            "label": estimate_sections.CATEGORY_LABELS[key],
            "difference": difference,
            "display": _signed(difference, UNIT_PER_SQM if per_sqm else UNIT_MONEY),
            "dearer": difference > 0,
        })

    peak = max((abs(row["difference"]) for row in rows), default=0.0)
    for row in rows:
        row["width_pct"] = round(abs(row["difference"]) / peak * 100, 1) if peak else 0
    rows.sort(key=lambda row: abs(row["difference"]), reverse=True)
    return rows


def _share_text(share):
    """Долю пишем с одним знаком, пока она меньше десяти процентов: разница
    между 0,4% и 1,6% там существеннее, чем между 28% и 28,4%."""
    if share is None:
        return ""
    if share < 10:
        return f"{share:.1f}%".replace(".", ",")
    return f"{share:.0f}%"


def _add_weights(rows, base_total):
    """Полоска доли раздела — по колонке базового проекта, и только по ней.

    Самый дорогой раздел базы занимает трек целиком, остальные — сколько
    приходится на них. Масштаб именно от крупнейшего раздела, а не от итога:
    иначе даже фасад со своими 28% занимал бы четверть трека, а всё, что
    меньше пяти процентов, слилось бы в точку.

    Раньше ширина бралась как максимум по всем колонкам сразу — и раздел,
    дорогой у соседнего проекта, рисовался длинной полоской, хотя у базы там
    стояла мелочь: гидроизоляция занимала 15% трека при доле в 0,4%.
    """
    values = [row["cells"][0]["value"] for row in rows]
    peak = max((value for value in values if value is not None), default=0.0)

    for row, value in zip(rows, values):
        row["width_pct"] = (
            round(value / peak * 100, 1) if value is not None and peak else 0
        )
        row["share"] = (
            value / base_total * 100 if value is not None and base_total else None
        )
        row["share_display"] = _share_text(row["share"])
        row["minor"] = row["share"] is not None and row["share"] < MINOR_SHARE


# --- удорожание по проектам ------------------------------------------------

# Порог, ниже которого движение считается округлением, а не удорожанием. Тот
# же рубль, что и в чтении файла удорожания: считать раздел «подорожавшим»
# из-за копейки нельзя, иначе частота «дорожает в 5 из 5» перестанет что-то
# значить.
INCREASE_EPSILON = 1.0


def _project_increase(slug, passport, report, adjustments):
    """Удорожание одного проекта — одной строкой для диаграммы.

    Деньги приводятся тем же множителем, что и всё остальное на странице: без
    этого проекты разных лет складывались бы в общий итог как есть. Процент
    множитель не задевает — он отношение внутри одного проекта, и поправка
    сокращается. Площадь — тоже: квадратный метр 2020 года это квадратный метр
    2026-го, поправляется только то, что в рублях.
    """
    factor, notes = project_factor(
        _source_vat(passport), passport.get("year_signed"), adjustments,
    )
    total = report.total
    # cost_increase.Row's money fields are Decimal (see cost_increase._amount)
    # — converted to float here, at the door into this module's own ratio-
    # and-factor arithmetic, same as _as_float_costs does for estimate costs.
    delta = float(total.delta) * factor
    area = passport.get("total_area_sqm") or None
    return {
        "slug": slug,
        "name": passport.get("project_name") or slug,
        "baseline": float(total.baseline) * factor,
        "delta": delta,
        "area": area,
        "per_sqm": delta / area if area else None,
        "per_sqm_display": _signed(delta / area, UNIT_PER_SQM) if area else "—",
        "percent": total.percent,
        "percent_display": cost_increase.format_percent(total.percent) or "—",
        "money_display": _signed(delta, UNIT_MONEY),
        "dearer": total.delta > INCREASE_EPSILON,
        "from_estimate": report.from_estimate,
        "notes": notes,
    }


def _work_rows(slugs, reports, factors, areas):
    """Виды работ по всем проектам сразу: как часто дорожают и на сколько.

    Частота считается от числа проектов, у которых этот вид работ вообще есть,
    а не от всех выбранных: раздела, которого у проекта нет, он не удорожал и
    не удержал, и записывать его в знаменатель нечестно.

    ₽/м² — по той же причине от площади только тех проектов, где этот вид
    работ есть. Делить на площадь всей выборки значило бы размазывать
    удорожание одного проекта по метрам остальных.
    """
    gathered = {}
    for slug in slugs:
        report = reports.get(slug)
        if report is None:
            continue
        for row in report.rows:
            entry = gathered.setdefault(row.key, {
                "key": row.key,
                "label": estimate_sections.CATEGORY_LABELS.get(row.key, row.key),
                "delta": 0.0,
                "area": 0.0,
                # Площадь известна у всех проектов, где этот вид работ есть.
                # Стоит хоть одному её не иметь — ₽/м² не считается вовсе:
                # сумма удорожания по всем проектам, поделённая на площадь
                # части из них, это не рубли на метр, а просто большое число.
                "areas_known": True,
                "projects_total": 0,
                "projects_up": 0,
                "percents": [],
            })
            entry["delta"] += float(row.delta) * factors[slug]
            entry["area"] += areas.get(slug) or 0.0
            entry["areas_known"] = entry["areas_known"] and bool(areas.get(slug))
            entry["projects_total"] += 1
            if row.delta > INCREASE_EPSILON:
                entry["projects_up"] += 1
            if row.percent is not None:
                entry["percents"].append(row.percent)

    rows = list(gathered.values())
    for row in rows:
        percents = row.pop("percents")
        row["avg_percent"] = sum(percents) / len(percents) if percents else None
        if row["avg_percent"] is not None:
            row["avg_percent_display"] = cost_increase.format_percent(row["avg_percent"])
        elif row["delta"] > INCREASE_EPSILON:
            # Работ, которых в сметах не было, ни у одного проекта: процента нет
            # ни у одной строки, и прочерк рядом с суммой в четыреста миллионов
            # читался бы как «неизвестно», а известно как раз всё.
            row["avg_percent_display"] = "новые работы"
        else:
            row["avg_percent_display"] = "—"
        row["frequency"] = row["projects_up"] / row["projects_total"]
        row["frequency_display"] = f'{row["projects_up"]} из {row["projects_total"]}'
        row["frequency_pct"] = round(row["frequency"] * 100, 1)
        row["delta_display"] = _signed(row["delta"], UNIT_MONEY)
        area = row.pop("area") if row.pop("areas_known") else None
        row["per_sqm"] = row["delta"] / area if area else None
        row["per_sqm_display"] = (
            _signed(row["per_sqm"], UNIT_PER_SQM) if row["per_sqm"] is not None else "—"
        )
        row["dearer"] = row["delta"] > INCREASE_EPSILON

    peak = max((abs(row["delta"]) for row in rows), default=0.0)
    for row in rows:
        row["width_pct"] = round(abs(row["delta"]) / peak * 100, 1) if peak else 0
    # Сначала то, что дороже всего обошлось, — это и есть ответ на «какие работы
    # максимально ведут к удорожанию». Частота стоит рядом отдельным столбцом, и
    # по ней таблицу можно переупорядочить на месте.
    rows.sort(key=lambda row: row["delta"], reverse=True)
    return rows


def _scale(rows, value_key, width_key):
    """Ширины полосок по крупнейшему значению в выборке."""
    peak = max(
        (abs(row[value_key]) for row in rows if row[value_key] is not None),
        default=0.0,
    )
    for row in rows:
        row[width_key] = (
            round(abs(row[value_key]) / peak * 100, 1)
            if row[value_key] is not None and peak else 0
        )


def build_increase_summary(slugs, passports, reports, adjustments):
    """Удорожание по выбранным проектам, или None, когда его не с чего считать.

    ``reports`` — ``{slug: cost_increase.Report | None}``: у проекта без файла
    удорожания его нет, и в расчёт он не идёт. Ни одного файла на всю выборку —
    блока на странице нет вовсе: таблица из прочерков не сообщает ничего.
    """
    reports = reports or {}
    with_data = [slug for slug in slugs if reports.get(slug) is not None]
    if not with_data:
        return None

    factors = {
        slug: project_factor(
            _source_vat(passports[slug]), passports[slug].get("year_signed"),
            adjustments,
        )[0]
        for slug in with_data
    }
    projects = [
        _project_increase(slug, passports[slug], reports[slug], adjustments)
        for slug in with_data
    ]

    # Шкала — по крупнейшему значению в выборке: самый подорожавший проект
    # занимает свою половину трека целиком, остальные — сколько приходится на
    # них. Фиксированная шкала здесь не годится, потому что удорожание бывает и
    # в один процент, и в сорок. У процента и у ₽/м² шкалы свои: это разные
    # величины, и мерить их одной линейкой нечем.
    _scale(projects, "percent", "width_pct")
    _scale(projects, "per_sqm", "per_sqm_width_pct")

    percents = [p["percent"] for p in projects if p["percent"] is not None]
    average_percent = sum(percents) / len(percents) if percents else None
    total_delta = sum(p["delta"] for p in projects)
    total_baseline = sum(p["baseline"] for p in projects)
    weighted = (total_delta / total_baseline * 100) if total_baseline else None

    # ₽/м² — только когда площадь известна у всех учтённых проектов. Иначе в
    # одном столбце стояли бы рубли на метр и рубли просто, а итог считался бы
    # по части выборки и выглядел бы как по всей.
    areas = {slug: passports[slug].get("total_area_sqm") or None for slug in with_data}
    per_sqm = all(areas.values())
    total_area = sum(areas.values()) if per_sqm else None
    total_per_sqm = total_delta / total_area if total_area else None

    return {
        "projects": projects,
        "works": _work_rows(with_data, reports, factors, areas),
        "per_sqm": per_sqm,
        "total_per_sqm": total_per_sqm,
        "total_per_sqm_display": (
            _signed(total_per_sqm, UNIT_PER_SQM) if total_per_sqm is not None else "—"
        ),
        "total_area": total_area,
        "average_percent": average_percent,
        "average_percent_display": cost_increase.format_percent(average_percent) or "—",
        "total_delta": total_delta,
        "total_delta_display": _signed(total_delta, UNIT_MONEY),
        # Средний процент и процент по сумме — разные числа, и разойтись они
        # могут сильно: маленький проект, подорожавший вдвое, тянет средний
        # вверх, а на сумму почти не влияет. Поэтому оба, и каждый подписан.
        "weighted_percent": weighted,
        "weighted_percent_display": cost_increase.format_percent(weighted) or "—",
        "projects_with_data": len(with_data),
        "projects_total": len(slugs),
        "without_estimate": [
            p["name"] for p in projects if not p["from_estimate"]
        ],
    }


# --- средние по объектам ----------------------------------------------------

GROUP_LABEL_ALL = "Все объекты"


def _grouped_slugs(slugs, passports, group_by):
    """``[(подпись строки, [слаги])]`` — одна строка на всю выборку без
    группировки, иначе одна на каждое встретившееся значение поля.

    Использует то же поле, ту же нормализацию года и то же «Не указано», что
    и фильтр списка проектов (``project_filter``) — переключатель этой
    таблицы и галочки там задают один и тот же вопрос, и отвечать на него
    по-разному было бы только путать.
    """
    if group_by is None:
        return [(GROUP_LABEL_ALL, list(slugs))]

    field, order = next(
        (field, order) for key, field, _label, order in project_filter.GROUPS
        if key == group_by
    )
    by_value = {}
    for slug in slugs:
        value = project_filter._value(passports[slug], field)
        by_value.setdefault(value, []).append(slug)

    return [
        (
            project_filter.NOT_SET_LABEL if value == project_filter.NOT_SET else value,
            by_value[value],
        )
        for value in project_filter._sorted_values(by_value, order)
    ]


def _average(values):
    return sum(values) / len(values) if values else None


def _project_factor_or_exclude(passport, adjustments):
    """The project's factor, or None if a correction is switched on but
    can't actually be applied to this object.

    ``project_factor`` itself never refuses — a project with no known
    signing year still gets a factor back, just 1.0, with the reason
    recorded as a note rather than acted on. That is right for a single
    project's own column, where the note sits right next to its own figure.
    An average mixes several projects into one number, and a 1.0 sitting
    quietly among genuinely adjusted factors doesn't read as "not adjusted"
    — it reads as "adjusted to no change", which is a different, wrong,
    claim. So here the note is not decoration: it means the object cannot
    honestly stand next to the others in this particular average, and the
    caller drops it — visibly, not silently — instead of blending it in.
    """
    factor, notes = project_factor(
        _source_vat(passport), passport.get("year_signed"), adjustments,
    )
    return None if notes else factor


def _averages_row(label, group_slugs, passports, costs_by_slug, adjustments):
    """Среднее за м² по смете и среднее по цене договора для одной строки
    таблицы.

    За м² — портфельное: сумма стоимости работ по всем объектам, у которых
    есть смета и площадь, делённая на сумму их площадей, а не среднее из
    отдельных ставок объектов. Простое среднее ставок даёт маленькому
    дорогому объекту тот же вес, что и крупному, и тянет число туда, где
    реальных денег на фоне остальных почти нет; портфельное отвечает на
    вопрос «сколько в среднем стоит квадратный метр во всей этой выборке
    денег», а не «какая тут типичная ставка».

    Цена по договору — всё ещё простое среднее по объектам, где она вписана:
    это не ставка на единицу чего-либо, портфельно взвешивать её не на что.

    Объект без сметы или без площади не участвует в среднем за м², но не
    выпадает из среднего по договору, если цена там есть, — и наоборот: это
    два разных вопроса, и у каждого свой знаменатель, отдельный от размера
    группы (``count``) — он остаётся её паспортом, а не подменяет собой ни
    один из знаменателей.
    """
    total_cost = 0.0
    total_area = 0.0
    per_sqm_count = 0
    contract_values = []
    excluded = []
    for slug in group_slugs:
        passport = passports[slug]
        factor = _project_factor_or_exclude(passport, adjustments)
        if factor is None:
            excluded.append(passport.get("project_name") or slug)
            continue
        costs = costs_by_slug.get(slug) or {}
        area = passport.get("total_area_sqm") or None
        if costs and area:
            total_cost += sum(costs.values()) * factor
            total_area += area
            per_sqm_count += 1
        price = passport.get("contract_price_rub")
        if price is not None:
            contract_values.append(price * factor)

    per_sqm_avg = total_cost / total_area if total_area else None
    contract_avg = _average(contract_values)
    return {
        "label": label,
        "count": len(group_slugs),
        "per_sqm_avg": per_sqm_avg,
        "per_sqm_display": _format_metric(per_sqm_avg, UNIT_PER_SQM),
        "per_sqm_count": per_sqm_count,
        "contract_avg": contract_avg,
        "contract_display": _format_metric(contract_avg, UNIT_MONEY),
        "contract_count": len(contract_values),
        "excluded": excluded,
    }


def _average_work_rows(slugs, passports, costs_by_slug, adjustments):
    """Средний ₽/м² по каждому виду работ, по всей выборке целиком — не
    зависит от переключателя группировки, который делит только строки выше.

    Портфельное, как и средняя за м² в строке выше: сумма стоимости этого
    вида работ по объектам, где он нашёлся в смете, делённая на сумму их
    площадей — не среднее из отдельных ставок объектов.

    «N из M»: M — у скольких выбранных объектов вообще есть смета (и, если
    поправки включены, применимая к ним), N — у скольких из них этот вид
    работ в смете нашёлся. M одно и то же для каждой строки — знаменатель
    не сокращается сам собой до строк, где вид работ и так уже нашёлся,
    иначе единственный объект с этим разделом читался бы как «1 из 1», то
    есть как стопроцентное покрытие вместо «1 из 10».
    """
    considered = []
    for slug in slugs:
        costs = costs_by_slug.get(slug)
        if not costs:
            continue
        passport = passports[slug]
        factor = _project_factor_or_exclude(passport, adjustments)
        if factor is None:
            continue
        considered.append((passport, costs, factor))

    total = len(considered)
    gathered = {}
    for passport, costs, factor in considered:
        area = passport.get("total_area_sqm") or None
        for key, amount in costs.items():
            entry = gathered.setdefault(
                key, {"key": key, "total_cost": 0.0, "total_area": 0.0, "with_section": 0},
            )
            entry["with_section"] += 1
            if area:
                entry["total_cost"] += amount * factor
                entry["total_area"] += area

    rows = []
    for entry in gathered.values():
        avg = entry["total_cost"] / entry["total_area"] if entry["total_area"] else None
        rows.append({
            "key": entry["key"],
            "label": estimate_sections.CATEGORY_LABELS[entry["key"]],
            "avg_per_sqm": avg,
            "avg_per_sqm_display": _format_metric(avg, UNIT_PER_SQM),
            "frequency_display": f'{entry["with_section"]} из {total}',
        })

    # Сначала то, что в среднем обходится дороже всего — как и в остальных
    # таблицах этой страницы, отсортированных по стоимости.
    rows.sort(
        key=lambda row: row["avg_per_sqm"] if row["avg_per_sqm"] is not None else -1.0,
        reverse=True,
    )
    return rows


def build_averages_table(slugs, passports, costs_by_slug, adjustments, group_by=None):
    """Средние показатели по выбранным объектам — за м² по смете и по цене
    договора, — плюс разбивка по видам работ на всю выборку.

    ``group_by`` — один из ``project_filter.GROUP_KEYS`` ("contractor",
    "class", "year"), чтобы разбить строки по генподрядчику, классу или году
    подписания вместо одной строки на всю выборку; None — одна строка.

    ``excluded`` — имена объектов, для которых включённая поправка (НДС или
    инфляция) неприменима: год подписания или ставка неизвестны. Такой
    объект убран из каждого среднего на этой странице, а не оставлен в нём
    со множителем 1.0 — иначе номинальная цифра тихо встала бы рядом с
    приведёнными, и среднее перестало бы отвечать на какой-либо один вопрос.

    None вместо таблицы, когда сравнивать нечего — список проектов пуст.
    """
    if not slugs:
        return None

    costs_by_slug = _as_float_costs(costs_by_slug)
    groups = _grouped_slugs(slugs, passports, group_by)
    rows = [
        _averages_row(label, group_slugs, passports, costs_by_slug, adjustments)
        for label, group_slugs in groups
    ]
    # Ungrouped, this already is the one row above — no separate figure to
    # compute. Grouped, it's the same aggregate the group rows split into
    # pieces, recomputed across all of them: what the collapsed table still
    # shows once the per-group breakdown is hidden.
    total = rows[0] if group_by is None else _averages_row(
        GROUP_LABEL_ALL, slugs, passports, costs_by_slug, adjustments
    )
    excluded = sorted({name for row in rows for name in row["excluded"]} | set(total["excluded"]))

    return {
        "group_by": group_by,
        "rows": rows,
        "total": total,
        "works": _average_work_rows(slugs, passports, costs_by_slug, adjustments),
        "excluded": excluded,
    }


def _deviation(own_value, peer_avg):
    """How far ``own_value`` sits from ``peer_avg``, as a percentage —
    positive above the average, negative below.

    Same "no basis for a ratio" case as удорожание's own percentage: a zero
    or unknown average isn't a 0% or 100% difference, it is no difference
    that can honestly be stated at all.
    """
    if own_value is None or not peer_avg:
        return {"deviation_pct": None, "deviation_display": "—"}
    pct = (own_value / peer_avg - 1.0) * 100.0
    return {"deviation_pct": pct, "deviation_display": cost_increase.format_percent(pct)}


def build_class_average_comparison(
    slug, passports, costs_by_slug, adjustments, excluded_work_keys=None,
):
    """One object's own cost against the portfolio average of every other
    object sharing its building class — "Средняя стоимость за м²" and each
    work type's ₽/м², each with the object's own figure and how many
    percent above or below the average it sits.

    The peer group is every other loaded project (``passports`` is expected
    to already carry all of them, not just a chosen few) with the same
    ``building_class`` — a "бизнес" object is only ever measured against
    other "бизнес" objects, never the whole portfolio at once, which would
    average across price tiers that were never meant to be compared.

    ``excluded_work_keys`` — work-type keys (``estimate_sections.CATEGORY_KEYS``)
    dropped from every project's estimate before anything on this page is
    computed — as if that section had never been in the smeta at all. Not
    just the row in the per-work-type table (and its bar on the chart):
    "Стоимость за м²" is rebuilt the same way, so a checked-off work type
    disappears from every figure on the page at once. Comparing "at equal
    terms" — some system a peer's estimate happens to be missing, say —
    means removing it everywhere, not leaving it baked into one number
    while it vanishes from another right next to it.

    None if the object itself carries no building class (nothing to match
    peers by) or no other loaded project shares it — there is then no
    average to hold it against, and a table of dashes would read as a
    computed answer rather than as "this can't be answered yet".
    """
    passport = passports[slug]
    building_class = passport.get("building_class")
    if not building_class:
        return None

    peer_slugs = [
        s for s in passports
        if s != slug and passports[s].get("building_class") == building_class
    ]
    if not peer_slugs:
        return None

    costs_by_slug = _as_float_costs(costs_by_slug)
    if excluded_work_keys:
        costs_by_slug = {
            s: {k: v for k, v in costs.items() if k not in excluded_work_keys}
            for s, costs in costs_by_slug.items()
        }
    peer_average = _averages_row(
        building_class, peer_slugs, passports, costs_by_slug, adjustments,
    )
    own = _averages_row(
        passport.get("project_name") or slug, [slug], passports, costs_by_slug, adjustments,
    )
    peer_works = {
        row["key"]: row
        for row in _average_work_rows(peer_slugs, passports, costs_by_slug, adjustments)
    }
    own_works = {
        row["key"]: row
        for row in _average_work_rows([slug], passports, costs_by_slug, adjustments)
    }

    work_rows = []
    for key in set(peer_works) | set(own_works):
        peer_row, own_row = peer_works.get(key), own_works.get(key)
        peer_value = peer_row["avg_per_sqm"] if peer_row else None
        own_value = own_row["avg_per_sqm"] if own_row else None
        work_rows.append({
            "key": key,
            "label": estimate_sections.CATEGORY_LABELS[key],
            "peer_avg": peer_value,
            "peer_avg_display": _format_metric(peer_value, UNIT_PER_SQM),
            "own_value": own_value,
            "own_display": _format_metric(own_value, UNIT_PER_SQM),
            **_deviation(own_value, peer_value),
        })
    work_rows.sort(
        key=lambda row: row["peer_avg"] if row["peer_avg"] is not None else -1.0,
        reverse=True,
    )

    per_sqm = {
        "peer_avg": peer_average["per_sqm_avg"],
        "peer_avg_display": peer_average["per_sqm_display"],
        "peer_avg_count": peer_average["per_sqm_count"],
        "own_value": own["per_sqm_avg"],
        "own_display": own["per_sqm_display"],
        **_deviation(own["per_sqm_avg"], peer_average["per_sqm_avg"]),
    }

    return {
        "building_class": building_class,
        "peer_count": len(peer_slugs),
        "per_sqm": per_sqm,
        "works": work_rows,
        "chart": _class_average_chart_rows(per_sqm, work_rows),
        "excluded": sorted(set(peer_average["excluded"]) | set(own["excluded"])),
    }


def _class_average_chart_rows(per_sqm, work_rows):
    """Bar-chart-ready rows for the class-average comparison — the same
    figures as its two tables (the ₽/м² summary, then every work type in
    the table's own order), each bar's height scaled against the single
    highest value on the page rather than its own row, so every pair of
    bars is honestly comparable to every other by eye.
    """
    rows = [{"key": "per_sqm", "label": "Стоимость за м²", **per_sqm}] + [
        {"key": row["key"], "label": row["label"], **row} for row in work_rows
    ]
    values = [
        v for row in rows for v in (row["peer_avg"], row["own_value"]) if v is not None
    ]
    max_value = max(values) if values else 1.0

    chart = []
    for row in rows:
        peer, own = row["peer_avg"], row["own_value"]
        chart.append({
            "key": row["key"],
            "label": row["label"],
            "peer_value": peer,
            "peer_display": row["peer_avg_display"],
            "peer_pct": round(peer / max_value * 100, 1) if peer else 0,
            "own_value": own,
            "own_display": row["own_display"],
            "own_pct": round(own / max_value * 100, 1) if own else 0,
            "deviation_pct": row.get("deviation_pct"),
            "deviation_display": row.get("deviation_display"),
        })
    return chart
