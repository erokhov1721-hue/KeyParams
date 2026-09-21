"""Сводка для инвесторов: смета, подписанное и прогнозируемое удорожание
по каждому объекту, и итоговая прогнозная стоимость — их сумма.

Ничего здесь не читает файлы и не знает про Flask — три словаря (смета,
отчёт по удорожанию, отчёт по прогнозируемому удорожанию) уже собраны в
другом месте (``app.routes``, теми же функциями, что читают их для страницы
объекта и страницы сравнения), этот модуль только сводит их в строки
таблицы.
"""

from decimal import Decimal

from . import cost_increase
from .passport import format_number

TOTAL_LABEL = "Итого"


def _money(value):
    if value is None:
        return "—"
    return f"{format_number(round(value))} ₽"


def _signed_money(value):
    if value is None:
        return "—"
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{format_number(round(abs(value)))} ₽"


def _money_per_sqm(value):
    # No " ₽/м²" suffix: every table this feeds already headers the column
    # "₽/м²", and repeating it on each row just adds noise next to a
    # neighbouring "Всего" column that does carry its own "₽" per row.
    if value is None:
        return "—"
    return format_number(round(value))


def _estimate_total(estimate_totals):
    """Смета объекта — сумма её разделов, или ``None``, если сметы нет /
    её не удалось разобрать (пустой словарь).

    Разделы приходят ``Decimal`` (как везде — прямиком из
    ``excel_report.estimate_costs``); переводится во ``float`` здесь же,
    как и остальные деньги этого модуля, — дальше с этой цифрой ничего,
    кроме сложения с другими такими же и показа на экране, не происходит.
    """
    if not estimate_totals:
        return None
    return float(sum(estimate_totals.values()))


def _signed_overrun(report):
    """Подписанное удорожание — «стало минус смета» из файла удорожания
    объекта. ``None``, если файла нет, или его дельта посчитана не против
    сметы (``from_estimate`` ложно): такая цифра сравнивает файл сам с
    собой («стало» против «было»), а не с базой, общей для всех объектов
    в этой сводке.
    """
    if report is None or not report.from_estimate:
        return None
    return float(report.total.delta)


def _percent(baseline, current):
    """Мера роста в процентах — та же формула, что и у ``cost_increase``
    и ``comparison`` для той же задачи: доля, на которую ``current``
    больше ``baseline``. ``None``, когда баланс — ноль (делить не на
    что), кроме случая, где и ``current`` ноль — тогда рост нулевой, а не
    неизвестный.
    """
    if not baseline:
        return None if current else 0.0
    return (float(current) / float(baseline) - 1.0) * 100.0


def _increasing_sections(report, predicted_report, estimate_totals, area):
    """Разделы сметы, которые дорожают — смета, подписанное и прогнозируемое
    удорожание порознь (та же разбивка, что и у объекта целиком в таблице
    выше), самый подорожавший в процентах первым (не по сумме в рублях —
    иначе маленький, но сильно подорожавший раздел тонул бы ниже большого,
    едва тронутого). Раздел, которого не было в смете вовсе (рост со «100 ₽»
    вниз ошибка не считать), встаёт первым — рост от нуля не выразить
    процентом, но это точно не «подорожал меньше всех». ``[]``, когда нет ни
    одного из двух источников: сравнивать тогда не с чем.

    Подписанное удорожание считается только когда есть смета, от которой
    его дельта отмерена (``report.from_estimate``) — иначе его «стало»
    сравнивалось само с собой, а не со сметой, и складывать его с прогнозом,
    который всегда мерен от сметы, значило бы сравнивать разное как одно.
    Раздел, которого в этом файле нет вовсе (при том что файл в принципе
    есть и сравним со сметой), не подорожал по нему ни на рубль — это ноль,
    а не «неизвестно», и то же самое для прогноза.

    Прогноз сам по себе — сумма удорожания по разделу (см.
    ``predicted_increase``, там нет пары «было»/«стало»), поэтому смета
    раздела берётся отдельно как база: раздел, которого в смете нет,
    стартует с нуля, и любая прогнозируемая сумма по нему — целиком
    новая работа.
    """
    has_signed = report is not None and report.from_estimate
    has_predicted = predicted_report is not None
    if not has_signed and not has_predicted:
        return []
    estimate_totals = {
        key: (value if isinstance(value, Decimal) else Decimal(str(value)))
        for key, value in (estimate_totals or {}).items()
    }
    signed_amounts, predicted_amounts, labels = {}, {}, {}
    if has_signed:
        for row in report.rows:
            signed_amounts[row.key] = signed_amounts.get(row.key, Decimal("0")) + row.delta
            labels[row.key] = row.label
    if has_predicted:
        for row in predicted_report.rows:
            predicted_amounts[row.key] = predicted_amounts.get(row.key, Decimal("0")) + row.amount
            labels[row.key] = row.label

    keys = set(signed_amounts) | set(predicted_amounts)
    totals = {
        key: signed_amounts.get(key, Decimal("0")) + predicted_amounts.get(key, Decimal("0"))
        for key in keys
    }
    candidates = []
    for key, amount in totals.items():
        if amount <= 0:
            continue
        baseline = estimate_totals.get(key, Decimal("0"))
        current = baseline + amount
        candidates.append((key, baseline, current, _percent(baseline, current)))
    # percent is None only for baseline == 0 with current > 0 ("новые
    # работы") — сорт ставит такие впереди (True > False), а не роняет их
    # в конец из-за отсутствующего числа.
    candidates.sort(key=lambda item: (item[3] is None, item[3] or 0.0), reverse=True)

    sections = []
    for key, baseline, current, percent in candidates:
        signed = float(signed_amounts.get(key, Decimal("0"))) if has_signed else None
        predicted = float(predicted_amounts.get(key, Decimal("0"))) if has_predicted else None
        estimate_per_sqm = _per_sqm(float(baseline), area)
        signed_per_sqm = _per_sqm(signed, area)
        predicted_per_sqm = _per_sqm(predicted, area)
        current_per_sqm = _per_sqm(float(current), area)
        sections.append({
            "label": labels[key],
            # Сырые числа — рядом со своими же "_display" строками, не
            # вместо них: таблица продолжает читать готовый текст, а
            # график (переключатель «таблица / график» на странице) берёт
            # числа отсюда напрямую, вместо того чтобы разбирать их обратно
            # из "12 345 ₽".
            "estimate": float(baseline),
            "signed": signed,
            "predicted": predicted,
            "current": float(current),
            "percent": percent,
            "estimate_per_sqm": estimate_per_sqm,
            "signed_per_sqm": signed_per_sqm,
            "predicted_per_sqm": predicted_per_sqm,
            "current_per_sqm": current_per_sqm,
            "estimate_display": _money(float(baseline)),
            "estimate_per_sqm_display": _money_per_sqm(estimate_per_sqm),
            "signed_display": _money(signed),
            "signed_per_sqm_display": _money_per_sqm(signed_per_sqm),
            "predicted_display": _money(predicted),
            "predicted_per_sqm_display": _money_per_sqm(predicted_per_sqm),
            "current_display": _money(float(current)),
            "per_sqm_display": _money_per_sqm(current_per_sqm),
            "percent_display": cost_increase.format_percent(percent) or "новые работы",
        })
    return sections


def _estimate_vs_total(estimate, total_cost):
    """Смета против итоговой стоимости — для полосы под таблицей, когда на
    странице выбран один объект. ``None``, если смета или итоговая
    стоимость неизвестны: сравнивать тогда не с чем.
    """
    if estimate is None or total_cost is None:
        return None
    overrun = total_cost - estimate
    percent = (total_cost / estimate - 1.0) * 100.0 if estimate else None
    return {
        "estimate_display": _money(estimate),
        "total_cost_display": _money(total_cost),
        "overrun_display": _signed_money(overrun),
        "percent": percent,
        "percent_display": cost_increase.format_percent(percent) or "—",
        "is_overrun": overrun > 0,
        "is_savings": overrun < 0,
    }


def _sum_present(values):
    """Сумма тех значений из ``values``, что не ``None`` — как
    ``_sum_known`` ниже, но по голому списку чисел, а не по колонке строк.
    ``None``, только если все величины неизвестны: отсутствие одного из
    трёх файлов не должно превращать всю итоговую стоимость в прочерк.
    """
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def _sum_known(rows, key):
    """Сумма известных значений колонки и их количество — раздельно от
    общего числа объектов: объект без цифры не тянет сумму к нулю и не
    портит средний градус происходящего, но виден в счётчике «N из
    всего»."""
    values = [row[key] for row in rows if row[key] is not None]
    return (sum(values) if values else None), len(values)


def _per_sqm(value, area):
    return value / area if value is not None and area else None


# Форма, которую ждёт статический app/static/waterfall.js для одной группы
# водопадной диаграммы «Разделы сметы, которые дорожают»: опорная строка
# («Смета») плюс пары «дельта → нарастающий итог» для подписанного и
# прогнозируемого удорожания. ``nativeUnit: "rub"`` говорит движку, что
# значения уже в рублях (не в процентах, как у его собственного тестового
# набора) — переключатель единиц «%»/«на м²» тогда переводит их через
# ``dgpAmount``/``areaSqm``, а не наоборот.
def _waterfall_groups(sections, area):
    return [
        {
            "name": section["label"],
            "bases": [{"label": "Смета", "value": section["estimate"]}],
            "deltas": [
                {
                    "deltaLabel": "Подписанное удорожание",
                    "cumulativeLabel": "с учётом подписанного удорожания",
                    "delta": section["signed"],
                    "color": "amber",
                },
                {
                    "deltaLabel": "Прогнозируемое удорожание",
                    "cumulativeLabel": "Итоговая стоимость",
                    "delta": section["predicted"],
                    "color": "danger",
                },
            ],
            "nativeUnit": "rub",
            "dgpAmount": section["estimate"],
            "areaSqm": area,
        }
        for section in sections
    ]


def _row(slug, label, estimate_totals, report, predicted, predicted_report, area, completed=False):
    estimate = _estimate_total(estimate_totals)
    signed = _signed_overrun(report)
    # Прогноз приходит ``Decimal`` из отчёта по прогнозируемому удорожанию —
    # тот же перевод, что и у сметы и у подписанного удорожания выше.
    predicted = float(predicted) if predicted is not None else None
    total_cost = _sum_present([estimate, signed, predicted])
    estimate_per_sqm = _per_sqm(estimate, area)
    predicted_per_sqm = _per_sqm(predicted, area)
    signed_per_sqm = _per_sqm(signed, area)
    total_per_sqm = _per_sqm(total_cost, area)
    sections = _increasing_sections(report, predicted_report, estimate_totals, area)
    return {
        "slug": slug,
        "label": label,
        "completed": completed,
        # Площадь объекта как есть — переключатель единиц «на м²» на
        # графике разделов делит на неё сам, тем же способом, что и
        # ``_per_sqm`` здесь, вместо того чтобы заново разбирать уже
        # готовые "_per_sqm_display" строки на странице.
        "area": area,
        "estimate": estimate,
        "estimate_display": _money(estimate),
        "estimate_per_sqm": estimate_per_sqm,
        "estimate_per_sqm_display": _money_per_sqm(estimate_per_sqm),
        "predicted": predicted,
        "predicted_display": _money(predicted),
        "predicted_per_sqm": predicted_per_sqm,
        "predicted_per_sqm_display": _money_per_sqm(predicted_per_sqm),
        "signed": signed,
        "signed_display": _money(signed),
        "signed_per_sqm": signed_per_sqm,
        "signed_per_sqm_display": _money_per_sqm(signed_per_sqm),
        "total_cost": total_cost,
        "total_cost_display": _money(total_cost),
        "total_per_sqm": total_per_sqm,
        "total_per_sqm_display": _money_per_sqm(total_per_sqm),
        "estimate_vs_total": _estimate_vs_total(estimate, total_cost),
        "has_increase_data": predicted_report is not None or (
            report is not None and report.from_estimate
        ),
        "increasing_sections": sections,
        "waterfall_groups": _waterfall_groups(sections, area),
    }


def _total_row(rows):
    estimate_total, estimate_count = _sum_known(rows, "estimate")
    predicted_total, predicted_count = _sum_known(rows, "predicted")
    signed_total, signed_count = _sum_known(rows, "signed")
    total_cost_total, total_cost_count = _sum_known(rows, "total_cost")
    return {
        "label": TOTAL_LABEL,
        "count": len(rows),
        "estimate_display": _money(estimate_total),
        "estimate_count": estimate_count,
        "predicted_display": _money(predicted_total),
        "predicted_count": predicted_count,
        "signed_display": _money(signed_total),
        "signed_count": signed_count,
        "total_cost_display": _money(total_cost_total),
        "total_cost_count": total_cost_count,
        # Портфельный % удорожания — по суммам всех объектов сразу, а не
        # среднее их собственных процентов: у объекта без сметы или без
        # итоговой стоимости свой процент попросту не посчитать, а тут он
        # всё равно вносит вклад в обе суммы там, где известен хоть один из
        # его составляющих.
        "estimate_vs_total": _estimate_vs_total(estimate_total, total_cost_total),
    }


def build_table(slugs, project_names, estimate_totals_by_slug,
                 cost_increase_reports_by_slug, predicted_increase_by_slug,
                 predicted_increase_reports_by_slug=None, area_by_slug=None,
                 completed_by_slug=None):
    """Строки инвесторской сводки, отсортированные по названию объекта, и
    итоговая строка под ними.

    ``project_names`` — ``{slug: имя}``. ``estimate_totals_by_slug`` —
    ``{slug: {раздел: сумма}}``, как отдаёт ``excel_report.estimate_costs``.
    ``cost_increase_reports_by_slug`` — ``{slug: cost_increase.Report |
    None}``. ``predicted_increase_by_slug`` — ``{slug: Decimal}``, итог
    ``predicted_increase.Report`` для объектов, у которых загружен файл
    прогнозируемого удорожания. ``predicted_increase_reports_by_slug`` —
    ``{slug: predicted_increase.Report | None}``, тот же отчёт целиком, по
    разделам — для карточки объекта, какие разделы дорожают. ``area_by_slug``
    — ``{slug: total_area_sqm | None}``, для ₽/м² там же. ``completed_by_slug``
    — ``{slug: bool}``, отметка «проект завершён» с его паспорта.
    """
    predicted_increase_reports_by_slug = predicted_increase_reports_by_slug or {}
    area_by_slug = area_by_slug or {}
    completed_by_slug = completed_by_slug or {}
    rows = [
        _row(
            slug, project_names.get(slug, slug),
            estimate_totals_by_slug.get(slug), cost_increase_reports_by_slug.get(slug),
            predicted_increase_by_slug.get(slug),
            predicted_increase_reports_by_slug.get(slug), area_by_slug.get(slug),
            completed_by_slug.get(slug, False),
        )
        for slug in slugs
    ]
    rows.sort(key=lambda row: row["label"])
    return {
        "rows": rows,
        "total": _total_row(rows),
        # Тот же «Итого», только по завершённым объектам — для строки под
        # таблицей, когда на странице выбран фильтр «Завершённые», той же
        # формой, что и «Итого» по всем объектам, а не средним чужих
        # процентов (см. комментарий у _total_row про портфельный %).
        "total_completed": _total_row([row for row in rows if row["completed"]]),
    }
