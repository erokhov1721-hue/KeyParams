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


def _add_deviations(cells):
    """How each project stands against the first one chosen.

    Against the first rather than against the cheapest: the first column is
    the one being asked about, and the rest are the yardstick.
    """
    base = cells[0]["value"] if cells else None
    if not base:
        return
    for cell in cells[1:]:
        if cell["value"] is None:
            continue
        cell["deviation"] = cell["value"] / base - 1.0
        cell["deviation_display"] = f"{cell['deviation'] * 100:+.0f}%".replace("-", "−")


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

    _add_weights(rows, columns)
    return {
        "columns": columns,
        "rows": rows,
        "total": {"label": "Итого СМР", "cells": total},
        "adjustments": adjustments,
    }


def _add_weights(rows, columns):
    """The bar beside each section, scaled against the priciest section shown.

    Scaled across the whole table rather than row by row: the point is that a
    facade is a third of the money and the process equipment a fraction of a
    per cent, which a per-row bar would flatten into every row looking equal.

    Only ₽/m² figures set the scale where there are any — a project with no
    area contributes roubles, and a billion of those next to a hundred
    thousand per square metre would leave every other bar invisible.
    """
    scaled = [index for index, column in enumerate(columns) if column["per_sqm"]]
    if not scaled:
        scaled = list(range(len(columns)))

    def values_of(row):
        return [
            row["cells"][index]["value"] for index in scaled
            if row["cells"][index]["value"] is not None
        ]

    peak = max((value for row in rows for value in values_of(row)), default=0.0)
    for row in rows:
        values = values_of(row)
        row["width_pct"] = round(max(values) / peak * 100, 1) if values and peak else 0
