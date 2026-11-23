"""Проверка по истории: каждый объект против остальных объектов своего
класса — где цифры выбиваются из обычного ряда.

Четыре отчёта из одних и тех же данных:

- ``data``     — пробелы и странности в самих данных (нет класса, площади,
  года; в смете мало разделов; одна и та же площадь у двух объектов);
- ``objects``  — цена за м² объекта целиком против середины его класса;
- ``works``    — то же по каждому виду работ, только выбившиеся строки;
- ``increase`` — доля удорожания к смете против середины класса.

Ничего здесь не читает файлы и не знает про Flask: паспорта, сметы по видам
работ и строки сводки по удорожанию уже собраны в routes.py теми же
функциями, что кормят «Сравнить со средним» и «Сводку по удорожанию», —
цифры здесь и там расходиться не могут.

«Середина класса» — медиана, а не среднее: один объект с задвоенной суммой
утянул бы среднее за собой и сам на его фоне выглядел бы приличнее. Медиану
один выброс не сдвигает.
"""
from statistics import median

from app import comparison, cost_increase, estimate_sections
from app.passport import format_number

# Сколько объектов класса с известной цифрой нужно, чтобы подсвечивать
# отклонения. Меньше — цифры показываются, но без оценки: середина из двух-
# трёх объектов — не норма, а просто два-три объекта.
MIN_GROUP = 4
# С этого числа сравнение считается уверенным; между MIN_GROUP и ним —
# «ориентировочно».
CONFIDENT_GROUP = 6

# Пороги подсветки, % от середины класса: (жёлтый, красный). У отдельных
# видов работ разброс естественно шире, чем у объекта целиком.
OBJECT_THRESHOLDS = (15.0, 30.0)
WORK_THRESHOLDS = (25.0, 50.0)
# Удорожание — в процентных пунктах от середины класса: сама доля — уже
# процент, и «на 50 % больше» от двух процентов ничего бы не значило.
INCREASE_THRESHOLDS = (10.0, 20.0)

# Объект, чья площадь меньше этой доли от середины класса, — «маленький»:
# цена за м² у таких обычно выше, и об этом говорится рядом с отклонением.
SMALL_AREA_SHARE = 0.5
# Смета, в которой видов работ меньше этой доли от обычного их числа,
# скорее всего прочитана не целиком.
FEW_SECTIONS_SHARE = 0.7

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_ALERT = "alert"
LEVEL_NONE = "none"   # сравнивать не с чем или группа слишком мала

NO_CLASS_LABEL = "Без класса"

EMPTY = "—"


def _level(deviation, thresholds):
    if deviation is None:
        return LEVEL_NONE
    warn, alert = thresholds
    size = abs(deviation)
    if size >= alert:
        return LEVEL_ALERT
    if size >= warn:
        return LEVEL_WARN
    return LEVEL_OK


def _money(value):
    return f"{format_number(round(value))} ₽" if value is not None else EMPTY


def _per_sqm(value):
    return f"{format_number(round(value))} ₽/м²" if value is not None else EMPTY


def _area(value):
    return f"{format_number(round(value))} м²" if value else EMPTY


def _signed_money(value):
    if value is None:
        return EMPTY
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{format_number(round(abs(value)))} ₽"


def _points(value):
    if value is None:
        return EMPTY
    if not round(value, 1):
        return "0 п.п."
    sign = "+" if value > 0 else "−"
    return f"{sign}{abs(value):.1f}".replace(".", ",") + " п.п."


def _confidence(count):
    if count >= CONFIDENT_GROUP:
        return "confident"
    if count >= MIN_GROUP:
        return "rough"
    return "few"


CONFIDENCE_LABELS = {
    "confident": "",
    "rough": "объектов немного — ориентир приблизительный",
    "few": "мало объектов для сравнения",
}


def _objects(passports, costs_by_slug, adjustments):
    """По объекту на строку: класс, площадь, год, множитель приведения и
    стоимость по видам работ уже в приведённых ценах."""
    costs_by_slug = comparison._as_float_costs(costs_by_slug)
    objects = []
    for slug, passport in passports.items():
        costs = costs_by_slug.get(slug) or {}
        factor, notes = comparison.project_factor(
            comparison._source_vat(passport), passport.get("year_signed"), adjustments,
        )
        comparable = not notes
        area = passport.get("total_area_sqm") or None
        total = sum(costs.values()) * factor if costs else None
        objects.append({
            "slug": slug,
            "name": passport.get("project_name") or slug,
            "building_class": passport.get("building_class") or None,
            "area": area,
            "year": comparison.parse_year(passport.get("year_signed")),
            "costs": {key: amount * factor for key, amount in costs.items()},
            "total": total,
            # Объект, к которому включённая поправка неприменима (нет года
            # или ставки НДС), в сравнение не идёт: номинальная цифра рядом
            # с приведёнными отвечала бы на другой вопрос.
            "comparable": comparable,
            "notes": notes,
            "rate": total / area if comparable and total and area else None,
        })
    objects.sort(key=lambda obj: obj["name"].lower())
    return objects


def _by_class(objects):
    groups = {}
    for obj in objects:
        if obj["building_class"]:
            groups.setdefault(obj["building_class"], []).append(obj)
    return groups


def _class_summaries(groups):
    rows = []
    for building_class, members in groups.items():
        rates = [obj["rate"] for obj in members if obj["rate"] is not None]
        confidence = _confidence(len(rates))
        rows.append({
            "building_class": building_class,
            "count": len(members),
            "compared": len(rates),
            "median": median(rates) if rates else None,
            "median_display": _per_sqm(median(rates) if rates else None),
            "confidence": confidence,
            "confidence_label": CONFIDENCE_LABELS[confidence],
        })
    rows.sort(key=lambda row: (-row["count"], row["building_class"]))
    return rows


def _object_rows(groups):
    rows = []
    for building_class, members in groups.items():
        rates = [obj["rate"] for obj in members if obj["rate"] is not None]
        areas = [obj["area"] for obj in members if obj["area"]]
        mid = median(rates) if rates else None
        mid_area = median(areas) if areas else None
        judged = len(rates) >= MIN_GROUP
        for obj in members:
            rate = obj["rate"]
            deviation = (rate / mid - 1.0) * 100.0 if rate is not None and mid else None
            small = bool(obj["area"] and mid_area and obj["area"] < mid_area * SMALL_AREA_SHARE)
            note = ""
            if rate is None:
                note = _why_no_rate(obj)
            elif not judged:
                note = CONFIDENCE_LABELS["few"]
            elif small and deviation is not None and deviation >= OBJECT_THRESHOLDS[0]:
                note = "маленький объект — цена за м² у таких обычно выше"
            rows.append({
                "slug": obj["slug"],
                "name": obj["name"],
                "building_class": building_class,
                "area": obj["area"],
                "area_display": _area(obj["area"]),
                "year": obj["year"],
                "rate": rate,
                "rate_display": _per_sqm(rate),
                "median": mid,
                "median_display": _per_sqm(mid),
                "deviation": deviation,
                "deviation_display": (
                    cost_increase.format_percent(deviation) if deviation is not None else EMPTY
                ),
                "level": _level(deviation, OBJECT_THRESHOLDS) if judged else LEVEL_NONE,
                "note": note,
            })
    rows.sort(key=_by_size_of("deviation"))
    return rows


def _why_no_rate(obj):
    if obj["total"] is None:
        return "нет сметы"
    if not obj["area"]:
        return "нет площади"
    if obj["notes"]:
        return "; ".join(obj["notes"])
    return ""


def _by_size_of(key):
    """Сначала красные, потом жёлтые, внутри — по величине отклонения;
    строки без оценки — в конце, по названию."""
    order = {LEVEL_ALERT: 0, LEVEL_WARN: 1, LEVEL_OK: 2, LEVEL_NONE: 3}

    def sort_key(row):
        value = row[key]
        return (order[row["level"]], -abs(value) if value is not None else 0.0, row["name"].lower())
    return sort_key


def _work_rows(groups):
    """Виды работ, чья цена за м² выбилась из середины класса, — только
    жёлтые и красные строки: в классе из 17 объектов по 14 разделов полная
    таблица была бы на 240 строк, из которых смотреть нужно на двадцать."""
    rows = []
    for building_class, members in groups.items():
        rated = [obj for obj in members if obj["rate"] is not None]
        for key in estimate_sections.CATEGORY_KEYS:
            values = {
                obj["slug"]: obj["costs"][key] / obj["area"]
                for obj in rated if obj["costs"].get(key)
            }
            if len(values) < MIN_GROUP:
                continue
            mid = median(values.values())
            if not mid:
                continue
            for obj in rated:
                own = values.get(obj["slug"])
                if own is None:
                    continue
                deviation = (own / mid - 1.0) * 100.0
                level = _level(deviation, WORK_THRESHOLDS)
                if level == LEVEL_OK:
                    continue
                impact = (own - mid) * obj["area"]
                rows.append({
                    "slug": obj["slug"],
                    "name": obj["name"],
                    "building_class": building_class,
                    "work_key": key,
                    "work_label": estimate_sections.CATEGORY_LABELS[key],
                    "own": own,
                    "own_display": _per_sqm(own),
                    "median": mid,
                    "median_display": _per_sqm(mid),
                    "group_count": len(values),
                    "deviation": deviation,
                    "deviation_display": cost_increase.format_percent(deviation),
                    # Сколько рублей на весь объект даёт это отклонение —
                    # по нему видно, какой раздел тянет объект целиком.
                    "impact": impact,
                    "impact_display": _signed_money(impact),
                    "level": level,
                })
    order = {LEVEL_ALERT: 0, LEVEL_WARN: 1}
    rows.sort(key=lambda row: (order[row["level"]], -abs(row["impact"]), row["name"].lower()))
    return rows


def _increase_rows(groups, summary_rows_by_slug):
    """Доля удорожания (подписанное и прогнозируемое) к смете вместе с
    прочими прямыми договорами — та же база и те же суммы, что у «Сводки по
    удорожанию», без поправок: это отношение двух сумм одного объекта.
    Объекты без данных об удорожании в середину класса не входят — у них не
    ноль, а неизвестно."""
    rows = []
    for building_class, members in groups.items():
        shares = {}
        for obj in members:
            summary = summary_rows_by_slug.get(obj["slug"])
            if not summary or not summary.get("has_increase_data") or not summary.get("base"):
                continue
            amount = (summary.get("signed") or 0.0) + (summary.get("predicted") or 0.0)
            shares[obj["slug"]] = (amount, amount / summary["base"] * 100.0)
        mid = median(share for _amount, share in shares.values()) if shares else None
        judged = len(shares) >= MIN_GROUP
        for obj in members:
            if obj["slug"] not in shares:
                continue
            amount, share = shares[obj["slug"]]
            deviation = share - mid
            rows.append({
                "slug": obj["slug"],
                "name": obj["name"],
                "building_class": building_class,
                "amount_display": _money(amount),
                "share": share,
                "share_display": cost_increase.format_percent(share).lstrip("+"),
                "median_display": cost_increase.format_percent(mid).lstrip("+"),
                "group_count": len(shares),
                "deviation": deviation,
                "deviation_display": _points(deviation),
                "level": _level(deviation, INCREASE_THRESHOLDS) if judged else LEVEL_NONE,
                "note": "" if judged else CONFIDENCE_LABELS["few"],
            })
    rows.sort(key=_by_size_of("deviation"))
    return rows


def _data_rows(objects):
    """Пробелы и странности в самих данных — то, из-за чего объект либо не
    попадает в сравнение, либо попадает с неверной цифрой."""
    section_counts = [len(obj["costs"]) for obj in objects if obj["costs"]]
    usual_sections = median(section_counts) if section_counts else None
    same_area = {}
    for obj in objects:
        if obj["area"]:
            same_area.setdefault(round(obj["area"], 2), []).append(obj["name"])

    rows = []

    def add(obj, level, problem, effect):
        rows.append({
            "slug": obj["slug"], "name": obj["name"],
            "building_class": obj["building_class"] or NO_CLASS_LABEL,
            "level": level, "problem": problem, "effect": effect,
        })

    for obj in objects:
        if not obj["building_class"]:
            add(obj, LEVEL_ALERT, "Не указан класс объекта",
                "в сравнение не попадает — не с кем сопоставлять")
        if not obj["area"]:
            add(obj, LEVEL_ALERT, "Не указана общая площадь",
                "цену за м² посчитать нельзя")
        if not obj["costs"]:
            add(obj, LEVEL_ALERT, "Нет сметы",
                "сравнивать нечего")
        elif usual_sections and len(obj["costs"]) < usual_sections * FEW_SECTIONS_SHARE:
            add(obj, LEVEL_WARN,
                f"В смете {len(obj['costs'])} видов работ — обычно их {round(usual_sections)}",
                "смета, возможно, прочитана не целиком: цена за м² может быть занижена")
        if obj["year"] is None:
            add(obj, LEVEL_WARN, "Не указан год подписания договора",
                "привести к сегодняшним ценам нельзя — в сравнение с поправкой на инфляцию не идёт")
        elif obj["notes"]:
            add(obj, LEVEL_WARN, "Поправка неприменима: " + "; ".join(obj["notes"]),
                "в сравнение не идёт")
        if obj["area"]:
            twins = [name for name in same_area[round(obj["area"], 2)] if name != obj["name"]]
            if twins:
                add(obj, LEVEL_WARN,
                    f"Площадь {_area(obj['area'])} — та же, что у «{'», «'.join(twins)}»",
                    "у двух разных объектов площадь обычно не совпадает — проверьте, чья она")

    order = {LEVEL_ALERT: 0, LEVEL_WARN: 1}
    rows.sort(key=lambda row: (order[row["level"]], row["name"].lower()))
    return rows


def _flagged(rows):
    return sum(1 for row in rows if row["level"] in (LEVEL_WARN, LEVEL_ALERT))


def build(passports, costs_by_slug, adjustments, summary_rows_by_slug=None,
          building_class=None):
    """Все четыре отчёта.

    ``passports`` — {slug: паспорт} всех объектов базы; ``costs_by_slug`` —
    {slug: {вид работ: сумма}} из сметы; ``adjustments`` — к чему привести
    цены (``comparison.Adjustments``); ``summary_rows_by_slug`` — {slug:
    строка «Сводки по удорожанию»}. ``building_class`` — показать только
    этот класс; середины при этом считаются так же, по всему классу.
    """
    objects = _objects(passports, costs_by_slug, adjustments)
    groups = _by_class(objects)
    classes = _class_summaries(groups)

    data_rows = _data_rows(objects)
    object_rows = _object_rows(groups)
    work_rows = _work_rows(groups)
    increase_rows = _increase_rows(groups, summary_rows_by_slug or {})

    if building_class:
        def keep(rows):
            return [row for row in rows if row["building_class"] == building_class]
        data_rows, object_rows = keep(data_rows), keep(object_rows)
        work_rows, increase_rows = keep(work_rows), keep(increase_rows)

    return {
        "classes": classes,
        "building_class": building_class,
        "data": data_rows,
        "objects": object_rows,
        "works": work_rows,
        "increase": increase_rows,
        "counts": {
            "data": len(data_rows),
            "objects": _flagged(object_rows),
            "works": len(work_rows),
            "increase": _flagged(increase_rows),
        },
        "thresholds": {
            "object": OBJECT_THRESHOLDS,
            "work": WORK_THRESHOLDS,
            "increase": INCREASE_THRESHOLDS,
            "min_group": MIN_GROUP,
        },
    }
