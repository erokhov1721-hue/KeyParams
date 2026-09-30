"""Анализ КП: сводная тендерная таблица подрядчиков против средней ₽/м² по
загруженным объектам того же класса.

Файл — сводная оценочная таблица тендера: слева номер раздела, статья и
наименование работ, правее — по блоку колонок на каждого подрядчика
(стоимость всего: материалы / СМР / косвенные / всего, «Комментарии»,
«Ожидаемая стоимость»). Этот модуль:

- ``parse_offer`` читает из неё блоки подрядчиков и строки разделов и
  подразделов (позиции внутри подразделов не нужны — оценка идёт не по ним);
- ``class_averages`` считает среднюю ₽/м² по виду работ по объектам класса —
  смета плюс подписанное и прогнозируемое удорожание, всё при НДС 22%;
- ``analyze`` сопоставляет одно с другим и решает, что написать в
  «Комментарии» и «Ожидаемую стоимость» каждого подрядчика;
- ``write_remarks`` вписывает это в исходный файл, не трогая остального.

Ничего здесь не знает про Flask и не читает файлы проектов: объекты
собирает ``app.routes`` теми же функциями, что и «Сводка по удорожанию».
"""

import io
import re
from collections import namedtuple
from decimal import Decimal

import openpyxl

from . import comparison, estimate_sections

# НДС, при котором подрядчики дают цены в тендерной таблице («с учетом НДС
# 22%»). Цены загруженных объектов приводятся к нему же, иначе сравнение
# шло бы между разными налоговыми базами.
OFFER_VAT_RATE = 22.0

# Пороги оценки раздела — отклонение предложения от ожидаемой стоимости.
HEAVILY_OVERPRICED_PCT = 30.0

# СМР больше этой доли от стоимости материалов — «необоснована стоимость СМР».
SMR_TO_MATERIALS_LIMIT = Decimal("0.5")

# Сумма меньше этой — не цена, а заглушка: подрядчики ставят 0,01 ₽ или
# 90 ₽ там, где раздел не расценивали, и специалист помечает такие строки
# «расценить» так же, как пустые.
NOMINAL_PRICE_LIMIT = Decimal("1000")

REMARK_OVERPRICED = "Завышена стоимость за раздел"
REMARK_HEAVILY_OVERPRICED = "Существенно завышена стоимость за раздел"
REMARK_PRICE_SECTION = "расценить раздел."
REMARK_PRICE_SUBSECTION = "расценить подраздел."
REMARK_UNJUSTIFIED_SMR = "необоснована стоимость СМР"

LEVEL_SECTION = "section"
LEVEL_SUBSECTION = "subsection"

HEADER_SEARCH_ROWS = 40

COMMENTS_HEADER = "комментарии"
EXPECTED_HEADER = "ожидаем"
COST_HEADER = "стоимость всего"
CUSTOMER_VOLUMES_HEADER = "заказчик"
NAME_ROW_HEADER = "наименование контрагента"
NUMBER_HEADER = "№ раздела"
ARTICLE_HEADER = "статья"
WORK_NAME_HEADER = "наименование работ"

SECTION_NUMBER_RE = re.compile(r"^\d+\.?$")
SUBSECTION_NUMBER_RE = re.compile(r"^\d+(\.\d+)+\.?$")
LOT_RE = re.compile(r"^лот\b", re.IGNORECASE)


class OfferError(Exception):
    """Файл — не сводная тендерная таблица, или в нём нечего сравнивать."""


# Колонки одного подрядчика (номера с единицы, как в openpyxl).
Contractor = namedtuple(
    "Contractor", "name materials_col smr_col total_col comment_col expected_col",
)

# Строка раздела или подраздела. ``amounts`` — по подрядчику, в порядке
# ``Offer.contractors``: ``(материалы, смр, всего)``, каждое Decimal или None.
Line = namedtuple("Line", "row number name level key amounts")

Offer = namedtuple("Offer", "contractors lines")

# Объект из базы: паспорт, смета по видам работ и два отчёта по удорожанию
# (любой может быть None) — в том виде, в каком их отдают ``app.routes``.
Project = namedtuple("Project", "name passport estimate signed_report predicted_report")

# ``per_sqm`` — {вид работ: ₽/м²}, ``counts`` — по скольким объектам,
# ``considered`` — сколько объектов класса вообще вошло в расчёт,
# ``excluded`` — имена объектов класса, выпавших из-за неизвестного НДС.
ClassAverages = namedtuple("ClassAverages", "per_sqm counts considered excluded")

# Что вписать в какую ячейку: текст замечания или ожидаемую стоимость.
Remark = namedtuple("Remark", "row col value")

# Одна клетка таблицы на странице: подрядчик × раздел.
Cell = namedtuple("Cell", "total per_sqm deviation_pct remark")
Section = namedtuple("Section", "row number name key label avg_per_sqm count expected cells")
Analysis = namedtuple("Analysis", "contractors sections remarks")


def _text(value):
    return " ".join(str(value).split()).lower() if value is not None else ""


def _amount(value):
    """Число из ячейки как Decimal, или None — пустая ячейка, текст,
    ошибка формулы вроде «#DIV/0!»."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return None


def _find_header_row(ws):
    for row in ws.iter_rows(min_row=1, max_row=HEADER_SEARCH_ROWS):
        if any(_text(cell.value) == COMMENTS_HEADER for cell in row):
            return row[0].row
    raise OfferError(
        "Не похоже на сводную тендерную таблицу: не нашлось колонки «Комментарии» "
        "у подрядчиков."
    )


def _find_col(ws, row, predicate, start=1, end=None):
    end = end or ws.max_column
    for col in range(start, end + 1):
        if predicate(_text(ws.cell(row, col).value)):
            return col
    return None


def _find_name_row(ws, header_row):
    for row in range(1, header_row):
        if _find_col(ws, row, lambda t: t == NAME_ROW_HEADER):
            return row
    return None


def _contractor(ws, header_row, name_row, start, comment_col, index):
    cost_cols = [
        col for col in range(start, comment_col)
        if _text(ws.cell(header_row, col).value).startswith(COST_HEADER)
        and CUSTOMER_VOLUMES_HEADER not in _text(ws.cell(header_row, col).value)
    ]
    if not cost_cols:
        return None
    # Первым в блоке может стоять ещё и «Расчетная стоимость» заказчика —
    # подрядчику принадлежит последняя такая колонка перед его комментариями.
    cost_col = cost_cols[-1]
    sub_row = header_row + 1
    within = cost_col + 4

    def sub(label):
        return _find_col(ws, sub_row, lambda t: t == label, cost_col, within)

    materials, smr, total = sub("материалы"), sub("смр"), sub("всего")
    if materials is None or smr is None or total is None:
        return None
    expected = comment_col + 1
    if EXPECTED_HEADER not in _text(ws.cell(header_row, expected).value):
        expected = None

    name = None
    if name_row is not None:
        for col in range(start, comment_col + 1):
            value = ws.cell(name_row, col).value
            if value is not None and str(value).strip() and _text(value) != NAME_ROW_HEADER:
                name = str(value).strip()
    return Contractor(
        name=name or f"Подрядчик {index}",
        materials_col=materials, smr_col=smr, total_col=total,
        comment_col=comment_col, expected_col=expected,
    )


def _level(number):
    if SECTION_NUMBER_RE.match(number):
        return LEVEL_SECTION
    if SUBSECTION_NUMBER_RE.match(number):
        return LEVEL_SUBSECTION
    return None


def parse_offer(source) -> Offer:
    """Блоки подрядчиков и строки разделов/подразделов первого листа.

    Суммы берутся такими, какими их последний раз посчитал Excel: формулы
    таблицы здесь не пересчитываются.
    """
    try:
        wb = openpyxl.load_workbook(source, data_only=True, read_only=True)
    except Exception as e:  # noqa: BLE001 — любой нечитаемый файл это одна и та же ошибка
        raise OfferError("Не удалось открыть файл как таблицу Excel.") from e
    try:
        ws = wb.worksheets[0]
        # read_only-лист не умеет ws.cell() за разумное время — нужные
        # строки шапки и данные читаются одним проходом в словарь.
        return _parse_sheet(_SheetView(ws))
    finally:
        wb.close()


class _SheetView:
    """Лист, прочитанный целиком в память: ``cell(row, col).value``, как у
    обычного листа openpyxl, но без его медленного доступа по ячейке в
    режиме read_only."""

    class _Cell:
        __slots__ = ("value", "row")

        def __init__(self, value, row):
            self.value = value
            self.row = row

    def __init__(self, ws):
        self._rows = [list(row) for row in ws.iter_rows(values_only=True)]
        self.max_row = len(self._rows)
        self.max_column = max((len(r) for r in self._rows), default=0)

    def cell(self, row, col):
        values = self._rows[row - 1] if 0 < row <= self.max_row else []
        value = values[col - 1] if 0 < col <= len(values) else None
        return self._Cell(value, row)

    def iter_rows(self, min_row, max_row):
        for row in range(min_row, min(max_row, self.max_row) + 1):
            yield [self.cell(row, col) for col in range(1, self.max_column + 1)]


def _parse_sheet(ws) -> Offer:
    header_row = _find_header_row(ws)
    name_row = _find_name_row(ws, header_row)

    comment_cols = [
        col for col in range(1, ws.max_column + 1)
        if _text(ws.cell(header_row, col).value) == COMMENTS_HEADER
    ]
    contractors = []
    start = 1
    for comment_col in comment_cols:
        contractor = _contractor(
            ws, header_row, name_row, start, comment_col, len(contractors) + 1,
        )
        if contractor is not None:
            contractors.append(contractor)
        start = comment_col + 1
    if not contractors:
        raise OfferError(
            "Не нашлось ни одного блока подрядчика: у колонки «Комментарии» нет "
            "колонок «Стоимость всего» с подписями «Материалы», «СМР», «Всего»."
        )

    number_col = _find_col(ws, header_row, lambda t: t == NUMBER_HEADER) or 2
    article_col = _find_col(ws, header_row, lambda t: t.startswith(ARTICLE_HEADER))
    name_col = _find_col(ws, header_row, lambda t: t.startswith(WORK_NAME_HEADER))

    lines = []
    for row in range(header_row + 2, ws.max_row + 1):
        number = str(ws.cell(row, number_col).value or "").strip()
        level = _level(number)
        if level is None:
            continue
        name = ""
        for col in (article_col, name_col):
            if col and ws.cell(row, col).value:
                name = " ".join(str(ws.cell(row, col).value).split())
                break
        if LOT_RE.match(name):
            continue
        amounts = [
            tuple(_amount(ws.cell(row, col).value)
                  for col in (c.materials_col, c.smr_col, c.total_col))
            for c in contractors
        ]
        lines.append(Line(
            row=row, number=number.rstrip("."), name=name, level=level,
            key=estimate_sections.classify(name), amounts=amounts,
        ))

    has_any_amount = any(
        amount is not None
        for line in lines if line.level == LEVEL_SECTION
        for amounts in line.amounts for amount in amounts
    )
    if not has_any_amount:
        raise OfferError(
            "В файле не нашлось ни одной суммы по разделам. Если таблица собрана "
            "формулами, откройте файл в Excel и сохраните его — тогда суммы "
            "появятся, и файл можно будет загрузить снова."
        )
    return Offer(contractors=contractors, lines=lines)


def project_costs(project):
    """{вид работ: Decimal} — смета объекта плюс подписанное и прогнозируемое
    удорожание по тому же виду работ.

    Подписанное — только если отчёт мерен от сметы (как в «Сводке по
    удорожанию»): иначе его дельта сравнивает файл сам с собой.
    """
    costs = dict(project.estimate or {})
    report = project.signed_report
    if report is not None and report.from_estimate:
        for row in report.rows:
            costs[row.key] = costs.get(row.key, Decimal("0")) + row.delta
    if project.predicted_report is not None:
        for row in project.predicted_report.rows:
            costs[row.key] = costs.get(row.key, Decimal("0")) + row.amount
    return costs


def class_averages(projects, building_class) -> ClassAverages:
    """Средняя ₽/м² по каждому виду работ по объектам ``building_class``.

    Портфельная, как на странице «Сравнить со средним»: сумма стоимостей
    вида работ по объектам, где он есть, делённая на сумму их площадей.
    Объект без сметы или площади не участвует; объект, чью ставку НДС не
    прочитать, выпадает и называется в ``excluded`` — приводить его к 22%
    не от чего.
    """
    adjustments = comparison.Adjustments(vat_rate=OFFER_VAT_RATE)
    totals, areas, counts = {}, {}, {}
    considered = 0
    excluded = []
    for project in projects:
        if (project.passport.get("building_class") or "") != building_class:
            continue
        area = project.passport.get("total_area_sqm") or None
        if not project.estimate or not area:
            continue
        factor = comparison._project_factor_or_exclude(project.passport, adjustments)
        if factor is None:
            excluded.append(project.name)
            continue
        considered += 1
        for key, cost in project_costs(project).items():
            totals[key] = totals.get(key, 0.0) + float(cost) * factor
            areas[key] = areas.get(key, 0.0) + float(area)
            counts[key] = counts.get(key, 0) + 1
    per_sqm = {key: totals[key] / areas[key] for key in totals if areas[key]}
    return ClassAverages(
        per_sqm=per_sqm, counts=counts, considered=considered, excluded=sorted(excluded),
    )


def _is_empty(amount):
    return amount is None or amount < NOMINAL_PRICE_LIMIT


def _unjustified_smr(materials, smr):
    if smr is None or smr <= 0:
        return False
    if not materials or materials <= 0:
        return True
    return smr > materials * SMR_TO_MATERIALS_LIMIT


def _section_verdict(deviation_pct):
    if deviation_pct is None or deviation_pct <= 0:
        return None
    if deviation_pct > HEAVILY_OVERPRICED_PCT:
        return REMARK_HEAVILY_OVERPRICED
    return REMARK_OVERPRICED


def _grouped(lines):
    """Разделы с подразделами под каждым, в порядке файла."""
    groups = []
    for line in lines:
        if line.level == LEVEL_SECTION:
            groups.append((line, []))
        elif groups:
            groups[-1][1].append(line)
    return groups


def analyze(offer, averages, area) -> Analysis:
    """Оценка каждого подрядчика по каждому разделу, который кто-то расценил.

    ``area`` — общая площадь объекта тендера, м².
    """
    area = float(area)
    remarks = []
    sections = []
    for section, subsections in _grouped(offer.lines):
        totals = [amounts[2] for amounts in section.amounts]
        if all(_is_empty(total) for total in totals):
            continue  # раздел вне тендера — его не расценил никто

        avg = averages.per_sqm.get(section.key) if section.key else None
        expected = avg * area if avg is not None else None
        cells = []
        for contractor, total in zip(offer.contractors, totals):
            per_sqm = float(total) / area if total is not None else None
            deviation = None
            remark = None
            if _is_empty(total):
                remark = REMARK_PRICE_SECTION
            elif expected:
                deviation = (float(total) / expected - 1.0) * 100.0
                remark = _section_verdict(deviation)
            if remark:
                remarks.append(Remark(section.row, contractor.comment_col, remark))
            if expected is not None and contractor.expected_col:
                remarks.append(Remark(section.row, contractor.expected_col, round(expected, 2)))
            cells.append(Cell(total=total, per_sqm=per_sqm, deviation_pct=deviation, remark=remark))

        for line in subsections:
            for contractor, (materials, smr, total) in zip(offer.contractors, line.amounts):
                if _is_empty(total):
                    remarks.append(Remark(line.row, contractor.comment_col, REMARK_PRICE_SUBSECTION))
                elif _unjustified_smr(materials, smr):
                    remarks.append(Remark(line.row, contractor.comment_col, REMARK_UNJUSTIFIED_SMR))

        sections.append(Section(
            row=section.row, number=section.number, name=section.name, key=section.key,
            label=estimate_sections.CATEGORY_LABELS.get(section.key) if section.key else None,
            avg_per_sqm=avg, count=averages.counts.get(section.key, 0) if section.key else 0,
            expected=expected, cells=cells,
        ))
    return Analysis(
        contractors=[c.name for c in offer.contractors], sections=sections, remarks=remarks,
    )


# Одна строка рейтинга: место (None — не расценено), подрядчик, стоимость,
# ₽/м², на сколько % дороже лучшего, отклонение от средней по классу,
# замечание по разделу, сколько разделов не расценено (для общего рейтинга).
RankRow = namedtuple(
    "RankRow",
    "place name total per_sqm vs_best_pct deviation_pct remark unpriced",
)
SectionRanking = namedtuple("SectionRanking", "section rows")
Ranking = namedtuple("Ranking", "overall expected_total sections")


def _pct(value, base):
    if value is None or not base:
        return None
    return (float(value) / float(base) - 1.0) * 100.0


def _ranked(rows):
    """Расценённые — от дешёвого к дорогому, с местами и разницей с лучшим;
    нерасценённые — в конце, без места."""
    priced = sorted((r for r in rows if r.total is not None), key=lambda r: r.total)
    unpriced = [r for r in rows if r.total is None]
    best = priced[0].total if priced else None
    return [
        r._replace(place=i + 1, vs_best_pct=_pct(r.total, best))
        for i, r in enumerate(priced)
    ] + unpriced


def rank(analysis, area) -> Ranking:
    """Предложения от лучшего к худшему по стоимости — всего и по каждому
    разделу.

    Общий итог — сумма разделов, которые подрядчик расценил; отклонение от
    средней по классу считается только по разделам, где средняя есть, чтобы
    подрядчик и ожидаемая стоимость складывались из одного и того же. Кто
    не расценил часть разделов, выглядит дешевле, чем есть, — поэтому рядом
    с ним стоит, сколько разделов не расценено.
    """
    area = float(area)
    expected_total = sum(s.expected for s in analysis.sections if s.expected) or None
    overall = []
    for index, name in enumerate(analysis.contractors):
        total = Decimal("0")
        comparable = Decimal("0")
        unpriced = 0
        for section in analysis.sections:
            cell = section.cells[index]
            if cell.remark == REMARK_PRICE_SECTION:
                unpriced += 1
                continue
            total += cell.total
            if section.expected:
                comparable += cell.total
        priced_any = unpriced < len(analysis.sections)
        overall.append(RankRow(
            place=None, name=name,
            total=total if priced_any else None,
            per_sqm=float(total) / area if priced_any else None,
            vs_best_pct=None,
            deviation_pct=_pct(comparable, expected_total) if priced_any and not unpriced else None,
            remark=None, unpriced=unpriced,
        ))

    sections = []
    for section in analysis.sections:
        rows = []
        for name, cell in zip(analysis.contractors, section.cells):
            priced = cell.remark != REMARK_PRICE_SECTION
            rows.append(RankRow(
                place=None, name=name,
                total=cell.total if priced else None,
                per_sqm=cell.per_sqm if priced else None,
                vs_best_pct=None, deviation_pct=cell.deviation_pct,
                remark=cell.remark, unpriced=0 if priced else 1,
            ))
        sections.append(SectionRanking(section=section, rows=_ranked(rows)))
    return Ranking(overall=_ranked(overall), expected_total=expected_total, sections=sections)


def write_remarks(source_bytes, remarks) -> bytes:
    """Исходный файл с вписанными ``remarks``, байтами .xlsx.

    Ячейка, где уже что-то есть (замечание, вписанное вручную), не
    перезаписывается. openpyxl не хранит посчитанные значения формул, поэтому
    книга помечается на полный пересчёт при открытии — иначе Excel показал
    бы в ней пустые итоги до первой правки.
    """
    wb = openpyxl.load_workbook(io.BytesIO(source_bytes))
    ws = wb.worksheets[0]
    for remark in remarks:
        cell = ws.cell(remark.row, remark.col)
        if not hasattr(cell, "column_letter"):
            continue  # не левая верхняя клетка объединённой области
        if cell.value is not None and str(cell.value).strip():
            continue
        cell.value = remark.value
    wb.calculation.fullCalcOnLoad = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
