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
    if value is None:
        return "—"
    return f"{format_number(round(value))} ₽/м²"


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


def _increasing_sections(predicted_report, estimate_totals, area):
    """Разделы сметы, которые дорожают по прогнозируемому удорожанию —
    крупнейший ₽/м² первым. ``[]`` без файла прогнозируемого удорожания:
    сравнивать тогда не с чем.

    Прогноз уже сам по себе — сумма удорожания по разделу (см.
    ``predicted_increase``, там нет пары «было»/«стало»), поэтому смета
    раздела берётся отдельно как база: раздел, которого в смете нет,
    стартует с нуля, и любая прогнозируемая сумма по нему — целиком
    новая работа.
    """
    if predicted_report is None:
        return []
    estimate_totals = {
        key: (value if isinstance(value, Decimal) else Decimal(str(value)))
        for key, value in (estimate_totals or {}).items()
    }
    increasing = sorted(
        (row for row in predicted_report.rows if row.amount > 0),
        key=lambda row: row.amount, reverse=True,
    )
    sections = []
    for row in increasing:
        baseline = estimate_totals.get(row.key, Decimal("0"))
        current = baseline + row.amount
        per_sqm = float(current) / area if area else None
        sections.append({
            "label": row.label,
            "estimate_display": _money(float(baseline)),
            "current_display": _money(float(current)),
            "per_sqm_display": _money_per_sqm(per_sqm),
            "percent_display": cost_increase.format_percent(
                _percent(baseline, current)
            ) or "новые работы",
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


def _row(slug, label, estimate_totals, report, predicted, predicted_report, area):
    estimate = _estimate_total(estimate_totals)
    signed = _signed_overrun(report)
    # Прогноз приходит ``Decimal`` из отчёта по прогнозируемому удорожанию —
    # тот же перевод, что и у сметы и у подписанного удорожания выше.
    predicted = float(predicted) if predicted is not None else None
    total_cost = _sum_present([estimate, signed, predicted])
    total_per_sqm = total_cost / area if total_cost is not None and area else None
    return {
        "slug": slug,
        "label": label,
        "estimate": estimate,
        "estimate_display": _money(estimate),
        "predicted": predicted,
        "predicted_display": _money(predicted),
        "signed": signed,
        "signed_display": _money(signed),
        "total_cost": total_cost,
        "total_cost_display": _money(total_cost),
        "total_per_sqm_display": _money_per_sqm(total_per_sqm),
        "estimate_vs_total": _estimate_vs_total(estimate, total_cost),
        "has_predicted_report": predicted_report is not None,
        "increasing_sections": _increasing_sections(predicted_report, estimate_totals, area),
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
    }


def build_table(slugs, project_names, estimate_totals_by_slug,
                 cost_increase_reports_by_slug, predicted_increase_by_slug,
                 predicted_increase_reports_by_slug=None, area_by_slug=None):
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
    — ``{slug: total_area_sqm | None}``, для ₽/м² там же.
    """
    predicted_increase_reports_by_slug = predicted_increase_reports_by_slug or {}
    area_by_slug = area_by_slug or {}
    rows = [
        _row(
            slug, project_names.get(slug, slug),
            estimate_totals_by_slug.get(slug), cost_increase_reports_by_slug.get(slug),
            predicted_increase_by_slug.get(slug),
            predicted_increase_reports_by_slug.get(slug), area_by_slug.get(slug),
        )
        for slug in slugs
    ]
    rows.sort(key=lambda row: row["label"])
    return {"rows": rows, "total": _total_row(rows)}
