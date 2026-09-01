"""Сводка для инвесторов: смета, прогнозируемое и подписанное удорожание
по каждому объекту, и дельта между ними.

Ничего здесь не читает файлы и не знает про Flask — три словаря
(смета, отчёт по удорожанию, прогноз ВИС) уже собраны в другом месте
(``app.routes``, теми же функциями, что читают их для страницы объекта
и страницы сравнения), этот модуль только сводит их в строки таблицы.
"""

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


def _sum_known(rows, key):
    """Сумма известных значений колонки и их количество — раздельно от
    общего числа объектов: объект без цифры не тянет сумму к нулю и не
    портит средний градус происходящего, но виден в счётчике «N из
    всего»."""
    values = [row[key] for row in rows if row[key] is not None]
    return (sum(values) if values else None), len(values)


def _row(slug, label, estimate_totals, report, predicted):
    estimate = _estimate_total(estimate_totals)
    signed = _signed_overrun(report)
    # Прогноз ВИС приходит ``Decimal`` из реестра — тот же перевод, что и у
    # сметы и у подписанного удорожания выше.
    predicted = float(predicted) if predicted is not None else None
    delta = predicted - signed if predicted is not None and signed is not None else None
    return {
        "slug": slug,
        "label": label,
        "estimate": estimate,
        "estimate_display": _money(estimate),
        "predicted": predicted,
        "predicted_display": _money(predicted),
        "signed": signed,
        "signed_display": _money(signed),
        "delta": delta,
        "delta_display": _signed_money(delta),
    }


def _total_row(rows):
    estimate_total, estimate_count = _sum_known(rows, "estimate")
    predicted_total, predicted_count = _sum_known(rows, "predicted")
    signed_total, signed_count = _sum_known(rows, "signed")
    delta_total, delta_count = _sum_known(rows, "delta")
    return {
        "label": TOTAL_LABEL,
        "count": len(rows),
        "estimate_display": _money(estimate_total),
        "estimate_count": estimate_count,
        "predicted_display": _money(predicted_total),
        "predicted_count": predicted_count,
        "signed_display": _money(signed_total),
        "signed_count": signed_count,
        "delta_display": _signed_money(delta_total),
        "delta_count": delta_count,
    }


def build_table(slugs, project_names, estimate_totals_by_slug,
                 cost_increase_reports_by_slug, vis_overrun_by_slug):
    """Строки инвесторской сводки, отсортированные по названию объекта, и
    итоговая строка под ними.

    ``project_names`` — ``{slug: имя}``. ``estimate_totals_by_slug`` —
    ``{slug: {раздел: сумма}}``, как отдаёт ``excel_report.estimate_costs``.
    ``cost_increase_reports_by_slug`` — ``{slug: cost_increase.Report |
    None}``. ``vis_overrun_by_slug`` — ``{slug: Decimal}``, только для
    объектов, которых реестр ВИС сопоставил хоть с одной своей строкой.
    """
    rows = [
        _row(
            slug, project_names.get(slug, slug),
            estimate_totals_by_slug.get(slug), cost_increase_reports_by_slug.get(slug),
            vis_overrun_by_slug.get(slug),
        )
        for slug in slugs
    ]
    rows.sort(key=lambda row: row["label"])
    return {"rows": rows, "total": _total_row(rows)}
