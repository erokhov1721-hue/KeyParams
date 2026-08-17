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

from . import estimate_sections, extractors, passport as passport_module
from .passport import format_number

DEFAULT_VAT_RATE = 22.0
DEFAULT_INFLATION = 12.0
DEFAULT_TARGET_YEAR = 2026

NOTE_NO_ESTIMATE = "смета не загружена"
NOTE_NO_AREA = "рубли, не ₽/м²: общая площадь неизвестна"
NOTE_NO_VAT = "без поправки на НДС: ставка неизвестна"
NOTE_NO_YEAR = "без поправки на инфляцию: год подписания неизвестен"

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


def adjustments_from_args(args) -> Adjustments:
    """Read the settings off the page's own address.

    Each correction has its own switch (``vat_on``, ``inflation_on``) rather
    than being turned on by the presence of a figure: an unticked checkbox
    submits nothing at all, which is exactly the behaviour wanted, and it
    keeps zero per cent — "bring these to one year, and tell me which ones
    have no year" — distinguishable from no correction at all.

    A switch that is on with an unreadable figure beside it falls back to the
    default rather than silently doing nothing.
    """
    vat = None
    if args.get("vat_on"):
        vat = parse_percent(args.get("vat"))
        if vat is None:
            vat = DEFAULT_VAT_RATE

    inflation = None
    if args.get("inflation_on"):
        inflation = parse_percent(args.get("inflation"))
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
        if source is None:
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


def _source_vat(passport):
    """The rate the estimate was priced at.

    Derived from the signing year first, exactly as the rest of the app does
    it — 20% through 2025, 22% from 2026. The passport's own ``vat`` field is
    only filled when a contract-terms protocol was uploaded, so relying on it
    would leave the correction inert on every project that hasn't got one.
    """
    year = parse_year(passport.get("year_signed"))
    return passport_module.vat_for_year(year) or passport.get("vat")


def _column(slug, passport, costs, adjustments):
    factor, notes = project_factor(
        _source_vat(passport), passport.get("year_signed"), adjustments,
    )
    area = passport.get("total_area_sqm")
    if not costs:
        notes.insert(0, NOTE_NO_ESTIMATE)
    elif not area:
        notes.insert(0, NOTE_NO_AREA)
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


# Шкала бара отклонения, ±%. Одна на всю таблицу: если у каждой строки она
# своя, полоски перестают сравниваться между собой и смысл теряется.
DEVIATION_SCALE = 50.0

# Ниже этой доли раздел приглушается. «Гидроизоляция» даёт +90%, но в деньгах
# это 503 ₽/м² при итоге 139 000 — ярко-красный процент там поднимает тревогу
# на ровном месте.
MINOR_SHARE = 1.0


def _add_bar(cell):
    """Двусторонний бар отклонения: влево дешевле, вправо дороже.

    Значение за пределами шкалы обрезается по краю трека и помечается — иначе
    +90% и +300% выглядели бы одинаково, и не было бы видно, что полоска
    упёрлась.
    """
    deviation = cell["deviation"]
    if deviation is None:
        cell["bar"] = None
        return
    percent = deviation * 100
    cell["bar"] = {
        "side": "right" if percent > 0 else "left" if percent < 0 else "zero",
        "width_pct": round(min(abs(percent), DEVIATION_SCALE) / DEVIATION_SCALE * 100, 1),
        "clipped": abs(percent) > DEVIATION_SCALE,
    }


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
        _add_bar(cell)


def build_section_table(slugs, passports, costs_by_slug, adjustments):
    """The section-by-section comparison, or None when there is nothing to show.

    Returns None if not one of the chosen projects has an estimate: a table of
    nothing but dashes only takes up the screen.
    """
    costs_by_slug = costs_by_slug or {}
    if not any(costs_by_slug.get(slug) for slug in slugs):
        return None

    columns = [
        _column(slug, passports[slug], costs_by_slug.get(slug) or {}, adjustments)
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

    costs_by_slug = costs_by_slug or {}
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

    return {
        "left": sides[0],
        "right": sides[1],
        "metrics": metrics,
        "sections": _section_deltas(sides),
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
