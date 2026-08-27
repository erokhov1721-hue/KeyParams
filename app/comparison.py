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

from . import cost_increase, estimate_sections, extractors, passport as passport_module
from . import project_filter
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
    delta = total.delta * factor
    area = passport.get("total_area_sqm") or None
    return {
        "slug": slug,
        "name": passport.get("project_name") or slug,
        "baseline": total.baseline * factor,
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
            entry["delta"] += row.delta * factors[slug]
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


def _averages_row(label, group_slugs, passports, costs_by_slug, adjustments):
    """Среднее за м² по смете и среднее по цене договора для одной строки
    таблицы — простое среднее по объектам, у которых нужная цифра есть.

    Объект без сметы или без площади не участвует в среднем за м², но не
    выпадает из среднего по договору, если цена там есть, — и наоборот: это
    два разных вопроса, и у каждого свой знаменатель.
    """
    per_sqm_values = []
    contract_values = []
    for slug in group_slugs:
        passport = passports[slug]
        factor, _notes = project_factor(
            _source_vat(passport), passport.get("year_signed"), adjustments,
        )
        costs = costs_by_slug.get(slug) or {}
        area = passport.get("total_area_sqm") or None
        if costs and area:
            per_sqm_values.append(sum(costs.values()) * factor / area)
        price = passport.get("contract_price_rub")
        if price is not None:
            contract_values.append(price * factor)

    per_sqm_avg = _average(per_sqm_values)
    contract_avg = _average(contract_values)
    return {
        "label": label,
        "count": len(group_slugs),
        "per_sqm_avg": per_sqm_avg,
        "per_sqm_display": _format_metric(per_sqm_avg, UNIT_PER_SQM),
        "contract_avg": contract_avg,
        "contract_display": _format_metric(contract_avg, UNIT_MONEY),
    }


def _average_work_rows(slugs, passports, costs_by_slug, adjustments):
    """Средний ₽/м² по каждому виду работ, по всей выборке целиком — не
    зависит от переключателя группировки, который делит только строки выше.

    «N из M»: M — у скольких выбранных объектов смета вообще содержит этот
    вид работ, N — у скольких из них к тому же известна площадь и цифра
    попала в среднее. Так видно, на скольких объектах в итоге основано число.
    """
    gathered = {}
    for slug in slugs:
        costs = costs_by_slug.get(slug)
        if not costs:
            continue
        passport = passports[slug]
        factor, _notes = project_factor(
            _source_vat(passport), passport.get("year_signed"), adjustments,
        )
        area = passport.get("total_area_sqm") or None
        for key, amount in costs.items():
            entry = gathered.setdefault(key, {"key": key, "values": [], "total": 0})
            entry["total"] += 1
            if area:
                entry["values"].append(amount * factor / area)

    rows = []
    for entry in gathered.values():
        avg = _average(entry["values"])
        rows.append({
            "key": entry["key"],
            "label": estimate_sections.CATEGORY_LABELS[entry["key"]],
            "avg_per_sqm": avg,
            "avg_per_sqm_display": _format_metric(avg, UNIT_PER_SQM),
            "frequency_display": f'{len(entry["values"])} из {entry["total"]}',
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

    None вместо таблицы, когда сравнивать нечего — список проектов пуст.
    """
    if not slugs:
        return None

    costs_by_slug = costs_by_slug or {}
    groups = _grouped_slugs(slugs, passports, group_by)
    rows = [
        _averages_row(label, group_slugs, passports, costs_by_slug, adjustments)
        for label, group_slugs in groups
    ]

    return {
        "group_by": group_by,
        "rows": rows,
        "works": _average_work_rows(slugs, passports, costs_by_slug, adjustments),
    }
