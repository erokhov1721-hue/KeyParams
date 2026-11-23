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
from math import exp, log
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


# --- Прогноз стоимости нового объекта ---------------------------------------
#
# Известны только класс и площадь. Прогноз складывается снизу вверх, по
# видам работ: для каждого — типичная цена за м² по объектам класса, где он
# есть (взвешенная медиана: объекты, близкие по площади, весят больше),
# умноженная на площадь нового объекта. Виды работ, которые есть меньше чем
# у половины объектов класса, входят в итог одной строкой «резерв на редкие
# работы» — каждая своей типичной ценой, умноженной на долю объектов, где
# она встречается. Совсем их не считать значило бы систематически занижать
# итог: у каждого второго-третьего объекта что-то из редкого да есть.
#
# Насколько прогнозу можно верить, не предполагается, а измеряется: каждый
# прошлый объект по очереди убирается из выборки и предсказывается по
# остальным — так же, как будет предсказан новый. Из того, как фактическая
# смета относилась к такому прогнозу, берутся и «обычная ошибка», и диапазон.
#
# На данных базы тем же способом проверялись другие способы (медиана цены
# за м² целиком, портфельное среднее, зависимость цены от площади по
# регрессии): сумма типичных цен по видам работ ошибается не больше любого
# из них, не ломается на одном выбросе и сразу даёт разбивку по работам.

# Ширина «окна близости» по площади, в натуральных логарифмах: объект в
# e ≈ 2,7 раза больше или меньше нового весит 0,61 от объекта той же
# площади, в 7 раз — 0,14. Окно намеренно широкое: объектов в классе
# немного, и узкое оставило бы прогноз на двух-трёх из них.
AREA_BANDWIDTH = 1.0
# Вид работ входит в итог своей строкой, если есть не меньше чем у этой
# доли объектов; реже — через резерв на редкие работы.
COMMON_SHARE = 0.5

# Прогноз на годы вперёд: сколько лет показывать (считая год, к которому
# приведены цены) и какие ставки роста цен брать для низкого и высокого
# сценария, если на странице не заданы свои.
HORIZON_YEARS = 4
DEFAULT_LOW_GROWTH = 8.0
DEFAULT_HIGH_GROWTH = 15.0

# Зоны риска — в каких видах работ ждать удорожания. Вид работ «вырос» у
# объекта, если доплата по нему больше этой доли его сметы, %.
RISK_GREW_PERCENT = 0.5
# Красная зона: ожидаемая доплата по виду работ не меньше стольких процентов
# всей сметы объекта, и росла она не меньше чем у двух третей объектов.
# Жёлтая — доплата заметна, но меньше или случается реже.
RISK_ALERT_POINTS = 2.0
RISK_WARN_POINTS = 0.75
RISK_OFTEN_SHARE = 2.0 / 3.0
# «Постоянная добавка»: вид работ дорожал не меньше чем у такой доли
# объектов, и даже у нижней четверти — не меньше чем на половину обычного.
# Такая доплата предсказуема: это не риск, а часть цены, которой нет в
# договоре (в том числе там, где договор занижен намеренно).
RISK_STEADY_SHARE = 0.8
RISK_STEADY_FLOOR = 0.5

FORECAST_NO_CLASS = "no_class"
FORECAST_NO_AREA = "no_area"
FORECAST_FEW = "few"


def _weighted_quantile(pairs, q):
    """Квантиль ``q`` (0…1) значений с весами — ``pairs`` это [(значение,
    вес)]. Между соседними значениями — линейно; при равных весах медиана
    чётного числа значений — середина между двумя центральными, как у
    обычной медианы."""
    pairs = sorted((value, weight) for value, weight in pairs if weight > 0)
    if not pairs:
        return None
    total = sum(weight for _value, weight in pairs)
    positions = []
    seen = 0.0
    for _value, weight in pairs:
        positions.append((seen + weight / 2.0) / total)
        seen += weight
    if q <= positions[0]:
        return pairs[0][0]
    if q >= positions[-1]:
        return pairs[-1][0]
    for index in range(1, len(pairs)):
        if q <= positions[index]:
            left, right = positions[index - 1], positions[index]
            share = (q - left) / (right - left) if right > left else 0.0
            return pairs[index - 1][0] + (pairs[index][0] - pairs[index - 1][0]) * share
    return pairs[-1][0]


def _area_weight(own_area, new_area):
    return exp(-0.5 * ((log(own_area) - log(new_area)) / AREA_BANDWIDTH) ** 2)


def _training_set(objects, building_class):
    """Объекты класса, по которым можно строить прогноз, и те, что пришлось
    оставить в стороне, — с причиной. Смета, в которой заметно меньше видов
    работ, чем обычно, в выборку не идёт: она занизила бы прогноз."""
    section_counts = [len(obj["costs"]) for obj in objects if obj["costs"]]
    usual_sections = median(section_counts) if section_counts else None
    used, skipped = [], []
    for obj in objects:
        if obj["building_class"] != building_class:
            continue
        count = len(obj["costs"])
        if obj["rate"] is None:
            skipped.append({"slug": obj["slug"], "name": obj["name"], "reason": _why_no_rate(obj)})
        elif usual_sections and count < usual_sections * FEW_SECTIONS_SHARE:
            skipped.append({
                "slug": obj["slug"], "name": obj["name"],
                "reason": f"в смете {count} видов работ — обычно их {round(usual_sections)}",
            })
        else:
            used.append(obj)
    return used, skipped


def _work_forecast(training, area):
    """Типичная цена за м² по каждому виду работ для объекта площадью
    ``area`` — строки по всем видам работ, что встречались в классе."""
    weights = {obj["slug"]: _area_weight(obj["area"], area) for obj in training}
    rows = []
    for key in estimate_sections.CATEGORY_KEYS:
        pairs = [
            (obj["costs"][key] / obj["area"], weights[obj["slug"]])
            for obj in training if obj["costs"].get(key)
        ]
        if not pairs:
            continue
        rows.append({
            "key": key,
            "count": len(pairs),
            "frequency": len(pairs) / len(training),
            "common": len(pairs) >= len(training) * COMMON_SHARE,
            "rate": _weighted_quantile(pairs, 0.5),
            "low": _weighted_quantile(pairs, 0.25),
            "high": _weighted_quantile(pairs, 0.75),
        })
    return rows


def _reserve_rate(work_rows):
    """Резерв на редкие виды работ, ₽/м²: цена каждого, умноженная на долю
    объектов, где он встречается."""
    return sum(row["rate"] * row["frequency"] for row in work_rows if not row["common"])


def _total_rate(work_rows):
    return sum(row["rate"] for row in work_rows if row["common"]) + _reserve_rate(work_rows)


def _predicted_rate(training, area):
    return _total_rate(_work_forecast(training, area))


def _backtest(training):
    """Проверка на прошлом: каждый объект предсказан по остальным. Список
    {объект, прогноз, факт, отношение факт/прогноз}; пусто, если после
    изъятия одного объекта остаётся слишком мало."""
    if len(training) < MIN_GROUP:
        return []
    results = []
    for obj in training:
        others = [other for other in training if other is not obj]
        predicted = _predicted_rate(others, obj["area"])
        if not predicted:
            continue
        results.append({
            "slug": obj["slug"], "name": obj["name"],
            "predicted": predicted, "actual": obj["rate"],
            "ratio": obj["rate"] / predicted,
        })
    return results


def _increase_shares(slugs, summary_rows_by_slug):
    shares = []
    for slug in slugs:
        summary = summary_rows_by_slug.get(slug)
        if not summary or not summary.get("has_increase_data") or not summary.get("base"):
            continue
        amount = (summary.get("signed") or 0.0) + (summary.get("predicted") or 0.0)
        shares.append(amount / summary["base"] * 100.0)
    return shares


def _work_increase_shares(slugs, costs_by_slug, increase_by_slug):
    """``{вид работ: [доплата к смете этого вида работ, %]}`` — по одному
    числу на каждый объект из ``slugs``, у которого известно удорожание и
    этот вид работ есть в смете. Объект, где вид работ не дорожал, даёт 0:
    «не выросло» — тоже опыт, и выбрасывать его значит завышать риск."""
    shares = {}
    for slug in slugs:
        extra = increase_by_slug.get(slug)
        if extra is None:
            continue
        for key, base in (costs_by_slug.get(slug) or {}).items():
            base = float(base or 0.0)
            if base > 0:
                shares.setdefault(key, []).append(float(extra.get(key) or 0.0) / base * 100.0)
    return shares


def _risk_rows(works, shares_by_key, total, increase):
    """Зоны риска: по каждому виду работ прогноза — как часто и на сколько
    он дорожал у прошлых объектов класса и сколько это в рублях для нового.

    Рубли по видам работ разложены так, чтобы вместе давать типичное
    удорожание класса (``increase``): сумма «типичных» доплат по отдельным
    работам сама по себе с ним не сходится, а проверка на прошлых объектах
    показала, что удорожание объекта целиком класс предсказывает не хуже.
    """
    rows = []
    for work in works:
        shares = shares_by_key.get(work["key"]) or []
        if not shares:
            continue
        pairs = [(share, 1.0) for share in shares]
        typical = median(shares)
        weight = 1.0 if work["common"] else work["frequency"]
        rows.append({
            "key": work["key"], "label": work["label"], "common": work["common"],
            "count": len(shares),
            "grew": sum(1 for share in shares if share > RISK_GREW_PERCENT),
            "typical": typical,
            "high": _weighted_quantile(pairs, 0.75),
            "low": _weighted_quantile(pairs, 0.25),
            "raw": max(work["amount"] * weight * typical / 100.0, 0.0),
        })
    raw_total = sum(row["raw"] for row in rows)
    scale = increase / raw_total if increase and raw_total else 1.0
    for row in rows:
        amount = row["raw"] * scale
        points = amount / total * 100.0 if total else 0.0
        often = row["grew"] >= row["count"] * RISK_OFTEN_SHARE
        if row["count"] < MIN_GROUP:
            level = LEVEL_NONE
        elif points >= RISK_ALERT_POINTS and often:
            level = LEVEL_ALERT
        elif points >= RISK_WARN_POINTS:
            level = LEVEL_WARN
        else:
            level = LEVEL_OK
        if row["count"] < MIN_GROUP:
            kind = "мало данных"
        elif row["typical"] <= RISK_GREW_PERCENT:
            kind = "обычно не дорожает"
        elif (row["grew"] >= row["count"] * RISK_STEADY_SHARE
              and row["low"] >= row["typical"] * RISK_STEADY_FLOOR):
            kind = "постоянная добавка"
        else:
            kind = "от случая к случаю"
        row.update({
            "amount": amount,
            "level": level,
            "kind": kind,
            "steady": kind == "постоянная добавка",
            "low_display": cost_increase.format_percent(row["low"]),
            "grew_display": f"{row['grew']} из {row['count']}",
            "typical_display": cost_increase.format_percent(row["typical"]),
            "high_display": cost_increase.format_percent(row["high"]),
            "amount_display": _money(amount),
            "points_display": _plain_percent(points),
            "part_display": (
                _plain_percent(amount / increase * 100.0) if increase else EMPTY
            ),
        })
    rows.sort(key=lambda row: -row["amount"])
    return rows


def _plain_percent(value):
    return f"{value:.1f}".replace(".", ",").replace("-", "−") + " %"


def _money_range(low, high):
    if low is None or high is None:
        return None
    return f"{_money(low)} – {_money(high)}"


def _horizon(total, area, share, base_year, main_rate, low_rate, high_rate):
    """Тот же прогноз, если договор подписать не в ``base_year``, а через
    год, два, три: смета растёт со ставкой сценария, типичное удорожание
    класса (``share``, % к смете) добавляется поверх.

    Рост цен считается только до года подписания. На годы самой стройки он
    не накручивается: удорожание класса — это и есть то, на сколько прошлые
    объекты подорожали за время стройки, рост цен в нём уже сидит, и второй
    раз его считать нельзя.
    """
    factor = 1.0 + (share or 0.0) / 100.0
    columns = []
    for step in range(HORIZON_YEARS):
        def grown(rate):
            return total * (1.0 + rate / 100.0) ** step

        estimate = grown(main_rate)
        final = estimate * factor
        columns.append({
            "year": base_year + step,
            "estimate_display": _money(estimate),
            "increase_display": _money(final - estimate) if share is not None else EMPTY,
            "final_display": _money(final),
            "final_per_sqm_display": _per_sqm(final / area),
            "low_display": _money(grown(low_rate) * factor),
            "high_display": _money(grown(high_rate) * factor),
            "growth_display": (
                cost_increase.format_percent(((1.0 + main_rate / 100.0) ** step - 1.0) * 100.0)
                if step else "сегодня"
            ),
        })
    return {
        "columns": columns,
        "main_rate_display": _plain_percent(main_rate),
        "low_rate_display": _plain_percent(low_rate),
        "high_rate_display": _plain_percent(high_rate),
        "has_increase": share is not None,
    }


def build_forecast(passports, costs_by_slug, adjustments, summary_rows_by_slug=None,
                   building_class=None, area=None, low_growth=DEFAULT_LOW_GROWTH,
                   high_growth=DEFAULT_HIGH_GROWTH, increase_by_slug=None):
    """Прогноз стоимости нового объекта класса ``building_class`` площадью
    ``area`` м² — по видам работ, с диапазоном и с проверкой на прошлых
    объектах. Цены — в тех же поправках (``adjustments``), что и остальная
    страница: с инфляцией это цена договора, подписанного в целевом году.

    ``low_growth`` и ``high_growth`` — ставки роста цен, % в год, для
    низкого и высокого сценария прогноза на годы вперёд; основной сценарий —
    ставка инфляции самой страницы.

    ``increase_by_slug`` — ``{slug: {вид работ: доплата, ₽}}``, подписанное
    и прогнозируемое удорожание прошлых объектов по видам работ; из него
    строятся зоны риска. Объекта без данных об удорожании в словаре нет.

    Всегда возвращает словарь; ``problem`` в нём — почему прогноза нет
    (не выбран класс, не задана площадь, в классе мало объектов).
    """
    summary_rows_by_slug = summary_rows_by_slug or {}
    result = {"building_class": building_class, "area": area, "problem": None}
    if not building_class:
        result["problem"] = FORECAST_NO_CLASS
        return result
    if not area or area <= 0:
        result["problem"] = FORECAST_NO_AREA
        return result

    objects = _objects(passports, costs_by_slug, adjustments)
    training, skipped = _training_set(objects, building_class)
    result["skipped"] = skipped
    result["training_count"] = len(training)
    if len(training) < MIN_GROUP:
        result["problem"] = FORECAST_FEW
        return result

    work_rows = _work_forecast(training, area)
    rate = _total_rate(work_rows)
    reserve = _reserve_rate(work_rows)
    total = rate * area

    works = []
    for row in work_rows:
        amount = row["rate"] * area
        low, high = format_number(round(row["low"])), format_number(round(row["high"]))
        works.append({
            "key": row["key"],
            "label": estimate_sections.CATEGORY_LABELS[row["key"]],
            "common": row["common"],
            "frequency": row["frequency"],
            "frequency_display": f"{row['count']} из {len(training)}",
            "rate": row["rate"],
            "rate_display": _per_sqm(row["rate"]),
            "range_display": f"{low} – {high}",
            "amount": amount,
            "amount_display": _money(amount),
            "reserve_display": _money(amount * row["frequency"]),
            "share_display": (
                _plain_percent(row["rate"] / rate * 100.0) if row["common"] and rate else EMPTY
            ),
        })
    works.sort(key=lambda row: (not row["common"], -row["amount"]))

    # Диапазон и точность — из проверки на прошлых объектах.
    backtest = _backtest(training)
    ratios = [(item["ratio"], 1.0) for item in backtest]
    errors = [(item["predicted"] / item["actual"] - 1.0) * 100.0 for item in backtest]
    sizes = sorted(abs(error) for error in errors)

    def scaled(q=None, pick=None):
        if not ratios:
            return None
        if pick is not None:
            return total * pick(value for value, _weight in ratios)
        return total * _weighted_quantile(ratios, q)

    likely_low, likely_high = scaled(0.25), scaled(0.75)

    # Удорожание: типичная для класса доля к смете — те же суммы, что в
    # «Сводке по удорожанию», по всем объектам класса, где они известны.
    class_slugs = [obj["slug"] for obj in objects if obj["building_class"] == building_class]
    shares = _increase_shares(class_slugs, summary_rows_by_slug)
    increase = final = final_low = final_high = None
    share_mid = share_low = share_high = None
    if shares:
        share_pairs = [(share, 1.0) for share in shares]
        share_mid = median(shares)
        share_low = _weighted_quantile(share_pairs, 0.25)
        share_high = _weighted_quantile(share_pairs, 0.75)
        increase = total * share_mid / 100.0
        final = total + increase
        if likely_low is not None:
            final_low = likely_low * (1.0 + share_low / 100.0)
            final_high = likely_high * (1.0 + share_high / 100.0)

    increase_by_slug = increase_by_slug or {}
    risks = _risk_rows(
        works, _work_increase_shares(class_slugs, costs_by_slug, increase_by_slug),
        total, increase,
    )

    # Та же смета по видам работ, но с допами: сколько вид работ стоит в
    # итоге. Раскладка та же, что в зонах риска, — в сумме даёт итоговую.
    extra_by_key = {row["key"]: row["amount"] for row in risks} if increase else {}
    for work in works:
        extra = extra_by_key.get(work["key"], 0.0)
        shown = bool(extra_by_key) and work["common"]
        work["extra_display"] = _money(extra) if shown else EMPTY
        work["with_extra_display"] = _money(work["amount"] + extra) if shown else EMPTY
    reserve_extra = sum(row["amount"] for row in risks if not row["common"])

    confidence = _confidence(len(training))
    result.update({
        "has_extra": bool(extra_by_key),
        "reserve_extra_display": _money(reserve_extra),
        "reserve_with_extra_display": _money(reserve * area + reserve_extra),
        "steady_count": sum(1 for row in risks if row["steady"]),
        "risks": risks,
        "risk_objects": sum(1 for slug in class_slugs if slug in increase_by_slug),
        "risk_alert_count": sum(1 for row in risks if row["level"] == LEVEL_ALERT),
        "area_display": _area(area),
        "confidence": confidence,
        "confidence_label": CONFIDENCE_LABELS[confidence],
        "works": works,
        "rare_count": sum(1 for row in works if not row["common"]),
        "reserve_rate_display": _per_sqm(reserve),
        "reserve_display": _money(reserve * area),
        "reserve_share_display": _plain_percent(reserve / rate * 100.0) if rate else EMPTY,
        "rate": rate,
        "rate_display": _per_sqm(rate),
        "total": total,
        "total_display": _money(total),
        "likely_display": _money_range(likely_low, likely_high),
        "extreme_display": _money_range(scaled(pick=min), scaled(pick=max)),
        "backtest_count": len(backtest),
        "typical_error_display": _plain_percent(median(sizes)) if sizes else None,
        "worst_error_display": _plain_percent(sizes[-1]) if sizes else None,
        "backtest": sorted(
            (
                {
                    "slug": item["slug"], "name": item["name"],
                    "predicted_display": _per_sqm(item["predicted"]),
                    "actual_display": _per_sqm(item["actual"]),
                    # Насколько прогноз промахнулся мимо факта.
                    "error": error,
                    "error_display": cost_increase.format_percent(error),
                }
                for item, error in zip(backtest, errors)
            ),
            key=lambda item: -abs(item["error"]),
        ),
        "increase_count": len(shares),
        "increase_share_display": _plain_percent(share_mid) if shares else None,
        "increase_range_display": (
            f"{_plain_percent(share_low)} – {_plain_percent(share_high)}" if shares else None
        ),
        "increase_display": _money(increase),
        "final": final,
        "final_display": _money(final),
        "final_per_sqm_display": _per_sqm(final / area) if final is not None else EMPTY,
        "final_likely_display": _money_range(final_low, final_high),
        "horizon": _horizon(
            total, area, share_mid, adjustments.target_year,
            adjustments.inflation if adjustments.inflation is not None
            else comparison.DEFAULT_INFLATION,
            low_growth, high_growth,
        ),
        "prices_as_signed": adjustments.inflation is None,
        "analogs": [
            {
                "slug": obj["slug"], "name": obj["name"], "year": obj["year"],
                "area_display": _area(obj["area"]),
                "rate_display": _per_sqm(obj["rate"]),
                "weight_display": f"{round(_area_weight(obj['area'], area) * 100)} %",
            }
            for obj in sorted(training, key=lambda obj: -_area_weight(obj["area"], area))
        ],
    })
    return result
