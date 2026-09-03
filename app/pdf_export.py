"""Страница сравнения, положенная на бумагу.

Печатная версия повторяет страницу целиком и в том же порядке: общие
сведения, диаграммы, стоимость по разделам, сравнение двух объектов. Всё, что
на экране нарисовано полосками — доля раздела, отклонение от базового
проекта, дельта между двумя объектами, — полосками и остаётся: в этих блоках
полоска и есть сообщение, а один столбец цифр читается совсем иначе.

Данные берутся ровно те же, что отдаёт страница (``comparison`` считает их
один раз для обеих), поэтому цифра на экране и цифра в файле разойтись не
могут — включая поправки на НДС и инфляцию, если они включены.
"""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from PIL import Image as PILImage

from . import chart_render, cost_increase

# ReportLab's built-in fonts only cover Latin-1 — every label here is
# Russian, so a system Cyrillic-capable TTF must be registered before any
# text is drawn, or Cyrillic characters render as blank boxes.
_FONT_DIR = Path(r"C:\Windows\Fonts")
_FONTS_REGISTERED = False

# Тот же знак, что в шапке страницы (``static/mr-logo.png``) — не отдельная
# картинка для файла, чтобы лого на экране и в PDF не могли разойтись.
_LOGO_PATH = Path(__file__).resolve().parent / "static" / "mr-logo.png"
_LOGO_HEIGHT = 20.0
_LOGO_READER = None

# Цвета — из светлой темы страницы: она и рассчитана на белый фон.
ACCENT = colors.HexColor("#12705c")
ACCENT_2 = colors.HexColor("#1c9a80")
RED = colors.HexColor("#c62828")
AMBER = colors.HexColor("#9a5b00")
INK = colors.HexColor("#13201e")
MUTED = colors.HexColor("#4f625f")
MUTED_2 = colors.HexColor("#6d807d")
GRID = colors.HexColor("#dfe3e2")
TRACK = colors.HexColor("#eef1f0")
HEAD_BG = colors.HexColor("#f4f8f6")
# Заливка таблицы «Стоимость по разделам» — то же ``--heat-savings``, что и
# на экране (см. style.css, светлая тема), не ACCENT: тот на странице значит
# «дешевле» только по историческому совпадению, а этот цвет привязан к
# заливке напрямую (см. comparison.py::_add_heat).
HEAT_SAVINGS = colors.HexColor("#378ade")

ACCENT_COLOR = ACCENT  # прежнее имя: на него мог ссылаться внешний код

CHART_DEFS = [
    ("price_by_year", "Цена работ по году подписания договора"),
    ("price_by_class", "Цена работ по классу жилья"),
    ("price", "Цена работ по проектам"),
    ("price_per_sqm", "Цена за м² по проектам"),
    ("concrete_coefficient", "Коэффициент монолита за общую площадь по СП, м³/м²"),
    ("facade_coefficient", "Коэффициент фасада за общую площадь по СП, м²(фас)/м²"),
    ("rebar_coefficient", "Коэффициент арматуры (средний), кг/м³"),
    ("concrete_materials_per_m3", "Материалы за 1 м³ бетона, ₽/м³"),
    ("concrete_works_per_m3", "СМР за 1 м³ бетона, ₽/м³"),
]

PAGE_SIZE = landscape(A4)
# Справка по одному объекту — не сравнение в несколько колонок, а лист
# фактов друг под другом, и книжная ориентация читается для такого
# документа привычнее альбомной.
PROJECT_PAGE_SIZE = A4
MARGIN = 28


def _ensure_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont("Arial", str(_FONT_DIR / "arial.ttf")))
    pdfmetrics.registerFont(TTFont("Arial-Bold", str(_FONT_DIR / "arialbd.ttf")))
    _FONTS_REGISTERED = True


def _logo_reader():
    global _LOGO_READER
    if _LOGO_READER is None:
        # Овал под буквами в исходном файле — непрозрачный белый, рассчитан
        # на тёмную подложку сайдбара сайта; на белой странице он и так не
        # виден. Но альфа-маска на резкой границе этого овала при масштабе
        # оставляет в PDF тонкий серый ободок — сведено к белому фону
        # заранее, чтобы картинка легла уже непрозрачной, без маски вовсе.
        rgba = PILImage.open(_LOGO_PATH).convert("RGBA")
        flat = PILImage.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.split()[3])
        _LOGO_READER = ImageReader(flat)
    return _LOGO_READER


def _draw_logo(canvas, doc):
    """Значок MR в правом верхнем углу — на каждой странице файла.

    Рисуется поверх готовой страницы, отдельно от потока абзацев и таблиц:
    в правом верхнем углу текста никогда не бывает, так что перекрыть
    содержимое ему нечем ни на одной из страниц.
    """
    reader = _logo_reader()
    width_px, height_px = reader.getSize()
    width = _LOGO_HEIGHT * width_px / height_px
    page_width, page_height = doc.pagesize
    x = page_width - MARGIN - width
    y = page_height - 6 - _LOGO_HEIGHT
    canvas.drawImage(reader, x, y, width=width, height=_LOGO_HEIGHT)


def _styles():
    return {
        "title": ParagraphStyle(
            "title", fontName="Arial-Bold", fontSize=17, leading=21,
            textColor=INK, spaceAfter=4,
        ),
        "heading": ParagraphStyle(
            "heading", fontName="Arial-Bold", fontSize=12, leading=15,
            textColor=INK, spaceBefore=14, spaceAfter=4,
        ),
        "subheading": ParagraphStyle(
            "subheading", fontName="Arial-Bold", fontSize=10, leading=13,
            textColor=INK, spaceBefore=10, spaceAfter=4,
        ),
        "sub": ParagraphStyle(
            "sub", fontName="Arial", fontSize=7.5, leading=10,
            textColor=MUTED, spaceAfter=6,
        ),
        "body": ParagraphStyle("body", fontName="Arial", fontSize=9, leading=12, textColor=INK),
        # Крупная цифра KPI-плитки: leading отдельно от «body» и с запасом
        # (16pt в строке высотой 12pt наезжает на подпись под ней).
        "tile_value": ParagraphStyle(
            "tile_value", fontName="Arial-Bold", fontSize=16, leading=20,
            textColor=INK, spaceAfter=3,
        ),
        "cell": ParagraphStyle("cell", fontName="Arial", fontSize=8, leading=10.5, textColor=INK),
        "cell_label": ParagraphStyle(
            "cell_label", fontName="Arial-Bold", fontSize=8, leading=10.5, textColor=INK,
        ),
        "cell_muted": ParagraphStyle(
            "cell_muted", fontName="Arial", fontSize=8, leading=10.5, textColor=MUTED,
        ),
        "cell_muted_right": ParagraphStyle(
            "cell_muted_right", fontName="Arial", fontSize=8, leading=10.5,
            textColor=MUTED, alignment=2,
        ),
        "cell_right": ParagraphStyle(
            "cell_right", fontName="Arial", fontSize=8, leading=10.5,
            textColor=INK, alignment=2,
        ),
        "head": ParagraphStyle(
            "head", fontName="Arial-Bold", fontSize=8, leading=10.5, textColor=INK,
        ),
        "note": ParagraphStyle(
            "note", fontName="Arial", fontSize=6.5, leading=8.5, textColor=AMBER,
        ),
    }


def _hex(color):
    """Цвет для разметки внутри абзаца — в том виде, в каком её читает
    reportlab: без решётки он принимает строку за десятичное число."""
    return "#" + color.hexval()[2:]


def _esc(text):
    """External text, made safe to sit inside a reportlab ``Paragraph``.

    A ``Paragraph`` parses its whole string as markup, not just the tags
    this module writes on purpose — a project name, an address, a contract
    term, or a line straight out of an uploaded workbook can carry "<", ">"
    or "&" with nothing to stop them being read as tags. Escaped here, once,
    at every point such text is about to become a paragraph, rather than
    trusted because it "just came from a form field".

    ``None`` passes through unchanged: several callers hand this a value
    that may or may not be there and decide the placeholder text themselves.
    """
    if text is None:
        return None
    return _xml_escape(str(text))


def _fade(color, amount=0.62):
    """Тот же цвет, выцветший к белому.

    Экран приглушает мелкие разделы прозрачностью; на печати надёжнее
    подмешать белого — результат тот же, а от поддержки прозрачности в
    просмотрщике не зависит.
    """
    return colors.Color(
        color.red + (1.0 - color.red) * amount,
        color.green + (1.0 - color.green) * amount,
        color.blue + (1.0 - color.blue) * amount,
    )


# --- Полоски ---------------------------------------------------------------

def _share_drawing(row, width, minor=False):
    """Доля раздела в смете базового проекта: полоска и рядом процент."""
    height = 9.0
    label_w = 26.0
    track_w = max(width - label_w - 4, 12.0)
    drawing = Drawing(width, height)
    drawing.hAlign = "LEFT"
    drawing.add(Rect(0, 1.5, track_w, height - 3, rx=2, ry=2,
                     fillColor=TRACK, strokeColor=None))
    filled = track_w * (row.get("width_pct") or 0) / 100.0
    if filled > 0:
        drawing.add(Rect(0, 1.5, filled, height - 3, rx=2, ry=2,
                         fillColor=MUTED_2 if minor else ACCENT_2, strokeColor=None))
    if row.get("share_display"):
        drawing.add(String(
            width, 2.2, row["share_display"], fontName="Arial", fontSize=6.5,
            textAnchor="end", fillColor=MUTED if minor else INK,
        ))
    return drawing


def _heat_fill_color(cell):
    """Фон ячейки таблицы разделов по силе отклонения, или None.

    Тот же расчёт, что красит плашку на экране (``comparison.py::_add_heat``,
    ``heat_mix``), но смешивается не с прозрачностью через ``color-mix()``
    (reportlab его не понимает), а прямо с белым фоном страницы — ячейка
    таблицы и так всегда на белом.
    """
    mix = cell.get("heat_mix")
    if mix is None:
        return None
    token = RED if cell["deviation"] > 0 else HEAT_SAVINGS
    fraction = mix / 100.0
    return colors.Color(
        token.red * fraction + (1 - fraction),
        token.green * fraction + (1 - fraction),
        token.blue * fraction + (1 - fraction),
    )


#  Ширина плашки на экране (``.sections-heat-value``) — 120px, ровно
#  переведённые в пункты (120 / 96 * 72): своя фиксированная величина, не
#  зависящая от ширины колонки. Колонка в PDF почти всегда куда шире
#  браузерной (там всего 1-2 проекта на всю ширину страницы, а не таблица со
#  скроллом), и заливка «вся ширина колонки минус небольшой отступ» на такой
#  колонке выглядит как сплошная полоса почти во всю ячейку — просвет слева
#  теряется на глаз. Фиксированная ширина решает это при любом числе
#  проектов: чем у́же колонка, тем заметнее становится просвет.
_HEAT_CHIP_WIDTH = 90.0


def _heat_drawing(cell, width, minor=False):
    """Плашка «40 059 −13%» на тепловой заливке — как на экране
    (``.sections-heat-value``): узкая, прижатая к правому краю ячейки, с
    просветом слева, а не заливка на всю ширину ячейки. Заливка на всю
    ширину на печати сливала бы соседние строки в одну сплошную цветную
    полосу без зазора между ними — там, где на экране от этого и спасает
    отдельная плашка вместо заливки самой ``<td>`` (см. comparison.py и
    style.css рядом с ``--heat-bg``).
    """
    height = 13.0
    pad_right = 8.0
    chip_w = min(_HEAT_CHIP_WIDTH, width)
    inset = width - chip_w

    drawing = Drawing(width, height)
    drawing.hAlign = "LEFT"

    fill = _heat_fill_color(cell)
    if fill is not None:
        drawing.add(Rect(inset, 0, chip_w, height, rx=3, ry=3,
                         fillColor=fill, strokeColor=None))

    percent = cell.get("deviation_display") or ""
    percent_w = pdfmetrics.stringWidth(percent, "Arial", 6.5) if percent else 0.0
    gap = 4.0 if percent else 0.0
    y = height / 2.0 - 2.6
    number_x = width - pad_right - percent_w - gap
    drawing.add(String(
        number_x, y, cell["display"], fontName="Arial", fontSize=8,
        textAnchor="end", fillColor=MUTED if minor else INK,
    ))
    if percent:
        drawing.add(String(
            width - pad_right, y, percent, fontName="Arial", fontSize=6.5,
            textAnchor="end", fillColor=MUTED,
        ))
    return drawing


def _two_sided_drawing(width, width_pct, dearer):
    """Полоска дельты между двумя объектами: влево дешевле, вправо дороже."""
    height = 10.0
    drawing = Drawing(width, height)
    drawing.hAlign = "LEFT"
    half = width / 2.0
    drawing.add(Rect(0, 2, width, height - 4, rx=2, ry=2,
                     fillColor=TRACK, strokeColor=None))
    drawing.add(Line(half, 0.8, half, height - 0.8, strokeColor=GRID, strokeWidth=0.7))
    length = max(half * (width_pct or 0) / 100.0, 0.0)
    if length:
        color = RED if dearer else ACCENT
        x = half if dearer else half - length
        drawing.add(Rect(x, 2, length, height - 4, rx=2, ry=2,
                         fillColor=color, strokeColor=None))
    return drawing


def _chart_bar_drawing(width, width_pct):
    height = 10.0
    drawing = Drawing(width, height)
    drawing.hAlign = "LEFT"
    drawing.add(Rect(0, 1, width, height - 2, rx=3, ry=3,
                     fillColor=TRACK, strokeColor=None))
    filled = width * (width_pct or 0) / 100.0
    if filled > 0:
        drawing.add(Rect(0, 1, filled, height - 2, rx=3, ry=3,
                         fillColor=ACCENT, strokeColor=None))
    return drawing


def _increase_frequency_drawing(width, frequency_pct):
    """«дорожает в»: доля проектов, где этот вид работ подорожал."""
    height = 5.0
    drawing = Drawing(width, height)
    drawing.hAlign = "LEFT"
    drawing.add(Rect(0, 0, width, height, rx=2, ry=2,
                     fillColor=TRACK, strokeColor=None))
    filled = width * (frequency_pct or 0) / 100.0
    if filled > 0:
        drawing.add(Rect(0, 0, filled, height, rx=2, ry=2,
                         fillColor=ACCENT_2, strokeColor=None))
    return drawing


def _increase_delta_drawing(width, width_pct, dearer):
    """«всего удорожания»: доля от наибольшей суммы в этой таблице."""
    height = 4.0
    drawing = Drawing(width, height)
    drawing.hAlign = "LEFT"
    drawing.add(Rect(0, 0, width, height, rx=2, ry=2,
                     fillColor=TRACK, strokeColor=None))
    filled = width * (width_pct or 0) / 100.0
    if filled > 0:
        drawing.add(Rect(0, 0, filled, height, rx=2, ry=2,
                         fillColor=RED if dearer else ACCENT, strokeColor=None))
    return drawing


# --- Блоки страницы -------------------------------------------------------

def _facts_block(passports, slugs, fields, field_labels, numeric_fields,
                 format_number, price_per_sqm, styles, page_width):
    """«Общие сведения» — та же таблица фактов, что и на странице."""
    header = [Paragraph("", styles["head"])]
    for slug in slugs:
        header.append(Paragraph(
            _esc(passports[slug].get("project_name") or slug), styles["head"]
        ))
    data = [header]

    for field in fields:
        if field == "project_name":
            continue
        row = [Paragraph(field_labels.get(field, field), styles["cell_label"])]
        for slug in slugs:
            value = passports[slug].get(field)
            if value is None:
                text = "—"
            elif field in numeric_fields:
                text = format_number(value)
            else:
                text = _esc(value)
            row.append(Paragraph(text, styles["cell"]))
        data.append(row)

        if field == "contract_price_rub":
            psqm_row = [Paragraph("Цена за м², руб.", styles["cell_label"])]
            for slug in slugs:
                psqm = price_per_sqm(passports[slug])
                psqm_row.append(Paragraph(
                    format_number(psqm) if psqm is not None else "—", styles["cell"]
                ))
            data.append(psqm_row)

    label_w = min(170.0, page_width * 0.28)
    value_w = (page_width - label_w) / max(len(slugs), 1)
    table = Table(data, colWidths=[label_w] + [value_w] * len(slugs), repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [Paragraph("Общие сведения", styles["heading"]), table]


def _terms_block(terms, slugs, passports, styles, page_width):
    """«Условия» — паспорт договора каждого проекта, колонка на проект."""
    if not terms:
        return []

    header = [Paragraph("", styles["head"])]
    for slug in slugs:
        header.append(Paragraph(
            _esc(passports[slug].get("project_name") or slug), styles["head"]
        ))
    data = [header]
    for row in terms["rows"]:
        line = [Paragraph(row["label"], styles["cell_label"])]
        for cell in row["cells"]:
            line.append(Paragraph(_esc(cell), styles["cell"]))
        data.append(line)

    label_w = min(170.0, page_width * 0.28)
    value_w = (page_width - label_w) / max(len(slugs), 1)
    table = Table(data, colWidths=[label_w] + [value_w] * len(slugs), repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [
        Paragraph("Условия", styles["heading"]),
        Paragraph("Из паспорта договора каждого проекта.", styles["sub"]),
        table,
    ]


def _charts_block(charts, styles, page_width):
    """Диаграммы — подпись, полоска, значение, как на экране (charts.js).

    Нулевые значения в саму полоску не идут — полоска нулевой длины рядом
    с обычными смотрелась бы как не отрисовавшийся баг, а не как «здесь и
    правда почти ничего», поэтому такие строки перечисляются отдельной
    строкой под таблицей вместо полоски, как и на странице.

    Ровно 2 сравниваемых проекта — под таблицей ещё разница между ними в %,
    тем же способом и тем же цветом (красный/зелёный), что и в «Сравнении
    двух объектов» ниже: все эти графики — цена и расход материалов, где
    меньше значит лучше, так что рост всегда красный.
    """
    story = []
    label_w = min(210.0, page_width * 0.32)
    value_w = 110.0
    bar_w = max(page_width - label_w - value_w - 12, 60.0)

    for key, title in CHART_DEFS:
        all_rows = charts.get(key) or []
        rows = [row for row in all_rows if not row.get("is_zero")]
        zero_rows = [row for row in all_rows if row.get("is_zero")]
        block = [Paragraph(title, styles["heading"])]
        if not rows:
            block.append(Paragraph("Недостаточно данных для этого графика.", styles["body"]))
            story.extend(block)
            continue
        data = [
            [
                Paragraph(_esc(row["label"]), styles["cell"]),
                _chart_bar_drawing(bar_w, row.get("width_pct")),
                Paragraph(row.get("display") or "", styles["cell_right"]),
            ]
            for row in rows
        ]
        table = Table(data, colWidths=[label_w, bar_w + 12, value_w])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, GRID),
        ]))
        block.append(table)
        if zero_rows:
            names = "«" + "», «".join(_esc(row["label"]) for row in zero_rows) + "»"
            block.append(Paragraph(
                f"Без сравнения на графике — значение округляется до нуля: {names}",
                styles["sub"],
            ))
        if len(rows) == 2 and rows[0]["value"]:
            percent = (rows[1]["value"] - rows[0]["value"]) / rows[0]["value"] * 100
            if round(abs(percent), 1):
                colour = _hex(RED if percent > 0 else ACCENT)
                delta_text = f'<font color="{colour}">{cost_increase.format_percent(percent)}</font>'
            else:
                delta_text = "0 %"
            block.append(Paragraph(f"Разница: {delta_text}", styles["sub"]))
        story.append(KeepTogether(block))
    return story


def _adjustments_line(adjustments):
    """Какие поправки применены — то, что на экране показывают галочки.

    В файле галочек нет, а без этой строки нельзя понять, что за цифры перед
    тобой: приведённые к одной ставке НДС и одному году или как в договоре.
    """
    if adjustments is None or not adjustments.applied:
        return "Поправки не применялись: цифры как в сметах."
    parts = []
    if adjustments.vat_rate is not None:
        parts.append(f"НДС приведён к ставке {adjustments.vat_display}%")
    if adjustments.inflation is not None:
        parts.append(
            f"инфляция {adjustments.inflation_display}% в год "
            f"к {adjustments.target_year} году"
        )
    return "Применены поправки: " + ", ".join(parts) + "."


def _sections_block(sections, styles, page_width):
    """«Стоимость по разделам» — с долей в смете и отклонениями."""
    if not sections:
        return []

    columns = sections["columns"]
    suffix = ", ₽/м²" if columns and columns[0]["per_sqm"] else ""
    story = [
        Paragraph(f"Стоимость по разделам{suffix}", styles["heading"]),
        Paragraph(
            "Доля — от итога базового проекта. Отклонение — к базовому проекту, "
            f"шкала ±50%. Базовый — «{_esc(columns[0]['name'])}». "
            + _adjustments_line(sections.get("adjustments")),
            styles["sub"],
        ),
    ]

    label_w = min(150.0, page_width * 0.22)
    weight_w = 86.0
    value_w = max((page_width - label_w - weight_w) / max(len(columns), 1), 70.0)

    header = [
        Paragraph("Раздел", styles["head"]),
        Paragraph("доля в смете", styles["head"]),
    ]
    for column in columns:
        cell = [Paragraph(_esc(column["name"]), styles["head"])]
        for note in column["notes"]:
            cell.append(Paragraph(note, styles["note"]))
        header.append(cell)
    data = [header]

    # Ячейки с заливкой по силе отклонения — собираются по ходу построения
    # строк и применяются к таблице отдельными командами BACKGROUND (после
    # шапки/подвала в style, чтобы для конкретной ячейки победила именно
    # заливка, а не общий HEAD_BG подвала).
    minor_rows = []
    for row in sections["rows"]:
        minor = bool(row.get("minor"))
        if minor:
            minor_rows.append(len(data))
        line = [
            Paragraph(row["label"], styles["cell_muted"] if minor else styles["cell"]),
            _share_drawing(row, weight_w - 12, minor),
        ]
        for cell in row["cells"]:
            line.append(_heat_drawing(cell, value_w - 12, minor))
        data.append(line)

    total = sections["total"]
    total_line = [Paragraph(total["label"], styles["cell_label"]), ""]
    for cell in total["cells"]:
        total_line.append(_heat_drawing(cell, value_w - 12))
    data.append(total_line)

    table = Table(
        data,
        colWidths=[label_w, weight_w] + [value_w] * len(columns),
        repeatRows=1,
    )
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("BACKGROUND", (0, -1), (-1, -1), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, -1), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    table.setStyle(TableStyle(style))
    story.append(table)
    return story


def _averages_block(averages, styles, page_width):
    """«Средние показатели по объектам» — те же две таблицы, что на экране:
    средние за м² и по цене договора (по всей выборке или по группам,
    смотря что было выбрано в переключателе), и средняя стоимость по видам
    работ, независимо от переключателя."""
    if not averages:
        return []

    total_count = sum(row["count"] for row in averages["rows"])
    story = [
        Paragraph("Средние показатели по объектам", styles["heading"]),
        Paragraph(
            f"Простое среднее по {total_count} выбранным объектам, с поправками "
            "на НДС и инфляцию, если они включены. У каждого среднего свой "
            "знаменатель — под цифрой указано, по скольким объектам из группы "
            "оно посчитано.",
            styles["sub"],
        ),
    ]
    if averages["excluded"]:
        names = "», «".join(_esc(name) for name in averages["excluded"])
        story.append(Paragraph(
            f'Не учтены в средних из-за включённой поправки — год подписания '
            f'или ставка НДС неизвестны: «{names}».',
            styles["sub"],
        ))

    label = "Группа" if averages["group_by"] else "Объекты"
    label_w = min(200.0, page_width * 0.34)
    rest_w = (page_width - label_w) / 3
    data = [[
        Paragraph(label, styles["head"]),
        Paragraph("объектов в группе", styles["head"]),
        Paragraph("средняя стоимость за м²", styles["head"]),
        Paragraph("средняя цена по договору", styles["head"]),
    ]]
    for row in averages["rows"]:
        data.append([
            Paragraph(_esc(row["label"]), styles["cell"]),
            Paragraph(str(row["count"]), styles["cell_right"]),
            [
                Paragraph(row["per_sqm_display"], styles["cell_right"]),
                Paragraph(f'{row["per_sqm_count"]} из {row["count"]}', styles["note"]),
            ],
            [
                Paragraph(row["contract_display"], styles["cell_right"]),
                Paragraph(f'{row["contract_count"]} из {row["count"]}', styles["note"]),
            ],
        ])
    table = Table(data, colWidths=[label_w, rest_w, rest_w, rest_w])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    story.append(Paragraph("Средняя стоимость по видам работ", styles["subheading"]))
    work_label_w = min(210.0, page_width * 0.4)
    work_rest = (page_width - work_label_w) / 2
    work_data = [[
        Paragraph("Вид работ", styles["head"]),
        Paragraph("средний ₽/м²", styles["head"]),
        Paragraph("есть у", styles["head"]),
    ]]
    for row in averages["works"]:
        work_data.append([
            Paragraph(row["label"], styles["cell"]),
            Paragraph(row["avg_per_sqm_display"], styles["cell_right"]),
            Paragraph(row["frequency_display"], styles["cell_right"]),
        ])
    work_table = Table(
        work_data, colWidths=[work_label_w, work_rest, work_rest], repeatRows=1,
    )
    work_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(work_table)
    return story


def _increase_block(increase, styles, page_width):
    """«Удорожание проектов» — те же плитки, диаграмма и таблица, что на экране."""
    if not increase:
        return []

    sub = (
        f'«Стало» против сметы, по файлам удорожания. Учтены '
        f'{increase["projects_with_data"]} из {increase["projects_total"]} выбранных '
        f'проектов — у остальных файла удорожания нет.'
    )
    if increase["without_estimate"]:
        names = "», «".join(_esc(name) for name in increase["without_estimate"])
        sub += f' У «{names}» нет сметы, поэтому там считалось от столбца «было».'

    story = [
        Paragraph("Удорожание проектов", styles["heading"]),
        Paragraph(sub, styles["sub"]),
    ]

    # Плитки — двумя ячейками в один ряд: крупная цифра и подпись под ней,
    # как на экране. Диаграммой одно число не рисуют ни там, ни здесь.
    tiles = [
        _tile(increase["average_percent_display"], "Средний % удорожания",
              "среднее по проектам", styles),
        _tile(increase["total_delta_display"], "Удорожание по всем проектам",
              f'{increase["weighted_percent_display"]} к сумме смет', styles),
    ]
    if increase["per_sqm"]:
        tiles.append(_tile(
            increase["total_per_sqm_display"], "Удорожание на м²",
            "на общую площадь всех проектов", styles,
        ))
    # Каждая плитка — своя рамка с зазором до соседней, а не один общий
    # прямоугольник на все три: между плитками добавлен пустой узкий столбец
    # без рамки, играющий роль зазора (аналог flex-gap на экране).
    tile_gap = 10.0
    tile_count = len(tiles)
    tile_w = (page_width - tile_gap * (tile_count - 1)) / tile_count
    tile_row, tile_col_widths = [], []
    for index, cell in enumerate(tiles):
        if index:
            tile_row.append("")
            tile_col_widths.append(tile_gap)
        tile_row.append(cell)
        tile_col_widths.append(tile_w)
    tiles_table = Table([tile_row], colWidths=tile_col_widths)
    tile_style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]
    for index in range(tile_count):
        col = index * 2
        tile_style.append(("BOX", (col, 0), (col, 0), 0.75, GRID))
        tile_style.append(("BACKGROUND", (col, 0), (col, 0), HEAD_BG))
    tiles_table.setStyle(TableStyle(tile_style))
    story.append(tiles_table)

    projects = increase["projects"]
    if len(projects) > 1:
        story += _increase_chart(
            "Общее увеличение стоимости по проектам", projects,
            "width_pct", "percent_display", "money_display", styles, page_width,
        )
        if increase["per_sqm"]:
            # Отдельной диаграммой, как и на экране: у процента и у ₽/м² разные
            # шкалы, и полоска, нарисованная по проценту, про рубли на метр не
            # говорит ничего.
            story += _increase_chart(
                "Удорожание на м² по проектам", projects,
                "per_sqm_width_pct", "per_sqm_display", None, styles, page_width,
            )

    story.append(Paragraph("Виды работ, которые делают смету дороже", styles["subheading"]))
    per_sqm = increase["per_sqm"]
    label_w = min(210.0, page_width * 0.34)
    columns = 4 if per_sqm else 3
    rest = max(page_width - label_w, 180.0) / columns
    head = [
        Paragraph("Вид работ", styles["head"]),
        Paragraph("дорожает в", styles["head"]),
        Paragraph("средний % удорожания", styles["head"]),
        Paragraph("всего удорожания", styles["head"]),
    ]
    if per_sqm:
        head.append(Paragraph("удорожание на м²", styles["head"]))
    data = [head]
    bar_w = max(rest - 12, 20.0)
    for row in increase["works"]:
        colour = RED if row["dearer"] else ACCENT
        line = [
            Paragraph(row["label"], styles["cell"]),
            [
                Paragraph(row["frequency_display"], styles["cell_right"]),
                _increase_frequency_drawing(bar_w, row["frequency_pct"]),
            ],
            Paragraph(row["avg_percent_display"], styles["cell_right"]),
            [
                Paragraph(
                    f'<font color="{_hex(colour)}">{row["delta_display"]}</font>',
                    styles["cell_right"],
                ),
                _increase_delta_drawing(bar_w, row["width_pct"], row["dearer"]),
            ],
        ]
        if per_sqm:
            line.append(Paragraph(
                f'<font color="{_hex(colour)}">{row["per_sqm_display"]}</font>',
                styles["cell_right"],
            ))
        data.append(line)
    table = Table(data, colWidths=[label_w] + [rest] * columns, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    return story


def _increase_chart(title, projects, width_key, value_key, note_key,
                    styles, page_width):
    """Диаграмма удорожания по проектам: подпись, двусторонняя полоска, значение."""
    story = [Paragraph(
        f'{title} <font size="7" color="{_hex(MUTED)}">'
        "влево — дешевле сметы, вправо — дороже</font>",
        styles["subheading"],
    )]
    label_w = min(180.0, page_width * 0.30)
    value_w = 120.0
    bar_w = max(page_width - label_w - value_w - 12, 60.0)

    data = []
    for project in projects:
        colour = RED if project["dearer"] else ACCENT
        value = f'<font color="{_hex(colour)}">{project[value_key]}</font>'
        if note_key:
            value += (
                f'<br/><font size="7" color="{_hex(MUTED)}">'
                f'{project[note_key]}</font>'
            )
        data.append([
            Paragraph(_esc(project["name"]), styles["cell"]),
            _two_sided_drawing(bar_w, project[width_key], project["dearer"]),
            Paragraph(value, styles["cell_right"]),
        ])
    table = Table(data, colWidths=[label_w, bar_w + 12, value_w])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, GRID),
    ]))
    story.append(table)
    return story


def _tile(value, label, note, styles):
    """Плитка со крупной цифрой — одной ячейкой таблицы."""
    return [
        Paragraph(value, styles["tile_value"]),
        Paragraph(label, styles["cell_label"]),
        Paragraph(note, styles["cell_muted"]),
    ]


def _pair_block(pair, styles, page_width):
    """«Сравнение двух объектов» — карточки и дельта по разделам."""
    if not pair:
        return []

    story = [
        Paragraph("Сравнение двух объектов", styles["heading"]),
        Paragraph(
            "Разница считается слева направо: как правый объект стоит против левого.",
            styles["sub"],
        ),
    ]

    label_w = min(190.0, page_width * 0.26)
    side_w = (page_width - label_w) / 3.0

    head = [
        Paragraph("", styles["head"]),
        Paragraph(_esc(pair["left"]["name"]), styles["head"]),
        Paragraph("разница", styles["head"]),
        Paragraph(_esc(pair["right"]["name"]), styles["head"]),
    ]
    data = [head]
    for metric in pair["metrics"]:
        delta = metric["delta_display"] or "—"
        if metric["dearer"] is True:
            delta = f'<font color="{_hex(RED)}">{delta}</font>'
        elif metric["dearer"] is False:
            delta = f'<font color="{_hex(ACCENT)}">{delta}</font>'
        if metric["diff_display"]:
            delta += (
                f'<br/><font size="7" color="{_hex(MUTED)}">'
                f'{metric["diff_display"]}</font>'
            )
        data.append([
            Paragraph(metric["label"], styles["cell_label"]),
            Paragraph(metric["left"], styles["cell_right"]),
            Paragraph(delta, styles["cell_right"]),
            Paragraph(metric["right"], styles["cell_right"]),
        ])

    table = Table(data, colWidths=[label_w, side_w, side_w, side_w], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        # Плотнее остальных таблиц: два блока пары рассчитаны уместиться на
        # одном листе, иначе последние разделы дельты уезжают на пустую
        # страницу и выглядят обрывком.
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    if not pair["sections"]:
        return story

    story.append(Paragraph("Дельта по разделам", styles["subheading"]))
    story.append(Paragraph("влево — дешевле, вправо — дороже", styles["sub"]))

    delta_label_w = min(220.0, page_width * 0.3)
    delta_value_w = 100.0
    track_w = max(page_width - delta_label_w - delta_value_w - 12, 80.0)
    rows = []
    for row in pair["sections"]:
        color = RED if row["dearer"] else ACCENT
        rows.append([
            Paragraph(row["label"], styles["cell"]),
            _two_sided_drawing(track_w, row.get("width_pct"), row["dearer"]),
            Paragraph(
                f'<font color="{_hex(color)}">{row["display"]}</font>',
                styles["cell_right"],
            ),
        ])
    delta_table = Table(rows, colWidths=[delta_label_w, track_w + 12, delta_value_w])
    delta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, GRID),
    ]))
    story.append(delta_table)
    return story


def build_compare_pdf(
    passports: dict, slugs: list, fields: list, field_labels: dict, charts: dict,
    numeric_fields=(), format_number=str, price_per_sqm=lambda data: None,
    sections=None, pair=None, terms=None, increase=None, averages=None,
) -> bytes:
    """Страница сравнения одним файлом.

    ``sections``, ``pair`` и ``terms`` — готовые блоки из ``comparison``, те же
    объекты, что уходят в шаблон страницы. Если их не передать, файл соберётся
    из того, что есть: блока без данных на странице тоже не бывает.
    """
    _ensure_fonts()
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=PAGE_SIZE, title="Сравнение проектов",
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
    )
    page_width = PAGE_SIZE[0] - doc.leftMargin - doc.rightMargin

    story = [Paragraph("Сравнение проектов", styles["title"])]
    story += _facts_block(
        passports, slugs, fields, field_labels, numeric_fields,
        format_number, price_per_sqm, styles, page_width,
    )
    story += _terms_block(terms, slugs, passports, styles, page_width)
    # Диаграммы — с новой страницы. Иначе первая из них ютится под таблицами
    # внизу листа, а остальные уезжают на следующий, и читать их приходится
    # вразбивку.
    story.append(PageBreak())
    story += _charts_block(charts, styles, page_width)
    sections_story = _sections_block(sections, styles, page_width)
    if sections_story:
        story.append(PageBreak())
        story += sections_story
    averages_story = _averages_block(averages, styles, page_width)
    if averages_story:
        story.append(PageBreak())
        story += averages_story
    increase_story = _increase_block(increase, styles, page_width)
    if increase_story:
        story.append(PageBreak())
        story += increase_story
    pair_story = _pair_block(pair, styles, page_width)
    if pair_story:
        story.append(PageBreak() if increase_story else Spacer(1, 10))
        story += pair_story

    doc.build(story, onFirstPage=_draw_logo, onLaterPages=_draw_logo)
    return buffer.getvalue()


# --- сравнение со средним по классу ------------------------------------------

def _class_average_block(result, project_name, styles, page_width):
    """«Сравнить со средним по классу» — тот же экран, тот же блок: средняя
    за м² и по видам работ против одного выбранного объекта, с отклонением
    в процентах."""
    if not result:
        return []

    story = [
        Paragraph(
            f'«{_esc(project_name)}» против среднего по классу '
            f'«{_esc(result["building_class"])}»',
            styles["heading"],
        ),
        Paragraph(
            f'Сравнение с {result["peer_count"]} другими загруженными объектами '
            f'класса «{_esc(result["building_class"])}». Стоимость за м² — '
            'портфельная: сумма стоимости работ делится на сумму площадей, а не '
            'усредняются ставки отдельных объектов. С поправками на НДС и '
            'инфляцию, если они включены.',
            styles["sub"],
        ),
    ]
    if result["excluded"]:
        names = "», «".join(_esc(name) for name in result["excluded"])
        story.append(Paragraph(
            f'Не учтены из-за включённой поправки — год подписания или ставка '
            f'НДС неизвестны: «{names}».',
            styles["sub"],
        ))

    label_w = min(200.0, page_width * 0.34)
    rest_w = (page_width - label_w) / 3
    per_sqm = result["per_sqm"]
    data = [
        [
            Paragraph("Показатель", styles["head"]),
            Paragraph("средняя по классу", styles["head"]),
            Paragraph(_esc(project_name), styles["head"]),
            Paragraph("отклонение", styles["head"]),
        ],
        [
            Paragraph("Стоимость за м²", styles["cell"]),
            [
                Paragraph(per_sqm["peer_avg_display"], styles["cell_right"]),
                Paragraph(
                    f'{per_sqm["peer_avg_count"]} из {result["peer_count"]}', styles["note"],
                ),
            ],
            Paragraph(per_sqm["own_display"], styles["cell_right"]),
            Paragraph(per_sqm["deviation_display"], styles["cell_right"]),
        ],
    ]
    table = Table(data, colWidths=[label_w, rest_w, rest_w, rest_w])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    story.append(Paragraph("Средняя стоимость по видам работ", styles["subheading"]))
    work_label_w = min(180.0, page_width * 0.3)
    work_rest = (page_width - work_label_w) / 3
    work_data = [[
        Paragraph("Вид работ", styles["head"]),
        Paragraph("средний ₽/м²", styles["head"]),
        Paragraph(f'{_esc(project_name)}, ₽/м²', styles["head"]),
        Paragraph("отклонение", styles["head"]),
    ]]
    for row in result["works"]:
        work_data.append([
            Paragraph(row["label"], styles["cell"]),
            Paragraph(row["peer_avg_display"], styles["cell_right"]),
            Paragraph(row["own_display"], styles["cell_right"]),
            Paragraph(row["deviation_display"], styles["cell_right"]),
        ])
    work_table = Table(
        work_data, colWidths=[work_label_w, work_rest, work_rest, work_rest], repeatRows=1,
    )
    work_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(work_table)
    return story


def _fitted_chart_image(png_bytes, max_width, max_height):
    """A rendered chart PNG as a reportlab flowable, scaled to fit the page.

    ``chart_render`` sizes its canvas in inches at its own fixed DPI, not in
    reportlab's points, and the category count it scales by has nothing to
    do with this page's own dimensions — so the natural size is computed
    from the PNG's own pixel dimensions and shrunk (never enlarged: a small
    chart blown up past its own resolution would just look soft) to fit
    what the page has left.
    """
    with PILImage.open(BytesIO(png_bytes)) as pil_image:
        width_px, height_px = pil_image.size
    natural_width = width_px * 72.0 / chart_render.DPI
    natural_height = height_px * 72.0 / chart_render.DPI
    ratio = min(max_width / natural_width, max_height / natural_height, 1.0)
    image = Image(BytesIO(png_bytes), width=natural_width * ratio, height=natural_height * ratio)
    image.hAlign = "CENTER"
    return image


def _class_average_chart_block(result, project_name, styles, page_width, page_height):
    """Тот же комбо-график, что и на экране (``chart_render``), на своей
    странице — рядом с таблицами он либо не помещается по высоте, либо
    сталкивает их на страницу дальше в произвольном месте."""
    png_bytes = chart_render.render_class_average_chart(result["chart"], project_name)
    heading = [
        Paragraph("Сравнение на графике", styles["heading"]),
        Paragraph(
            "Столбики — доля от самого большого значения на графике; линия — "
            f'отклонение «{_esc(project_name)}» от средней по классу, %.',
            styles["sub"],
        ),
    ]
    heading_height = sum(style.spaceBefore + style.leading + style.spaceAfter
                         for style in (styles["heading"], styles["sub"]))
    image = _fitted_chart_image(png_bytes, page_width, page_height - heading_height)
    return heading + [image]


def build_class_average_pdf(result, project_name) -> bytes:
    """«Сравнить со средним по классу» — тот же блок, что на экране, одним
    файлом. ``result`` — то, что вернул
    ``comparison.build_class_average_comparison``; вызывающий отвечает за
    то, чтобы он не был None — файл без данных на этой странице не бывает.
    """
    _ensure_fonts()
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=PAGE_SIZE, title="Сравнение со средним по классу",
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
    )
    page_width = PAGE_SIZE[0] - doc.leftMargin - doc.rightMargin
    page_height = PAGE_SIZE[1] - doc.topMargin - doc.bottomMargin

    story = [Paragraph("Сравнение со средним по классу", styles["title"])]
    story += _class_average_block(result, project_name, styles, page_width)
    story.append(PageBreak())
    story += _class_average_chart_block(result, project_name, styles, page_width, page_height)

    doc.build(story, onFirstPage=_draw_logo, onLaterPages=_draw_logo)
    return buffer.getvalue()


# --- справка по одному объекту ----------------------------------------------
#
# Тот же набор карточек, что на странице проекта, минус сама смета: там,
# где смета нужна, эту справку и печатают — смотреть в файле в саму смету
# незачем, а с тысячами строк она ещё и раздула бы файл до неприличных
# размеров. Удорожание в справку входит: это не смета, а отдельный, уже
# посчитанный отчёт по видам работ.


def _project_cover_image(cover_path, max_width, max_height):
    """Картинка объекта, вписанная в отведённый прямоугольник — или None,
    если обложки нет или прочитать её не удалось (битый файл, формат без
    поддержки в Pillow). Не увеличивается сверх своего размера — маленькая
    обложка так и остаётся маленькой, а не расплывается."""
    if not cover_path:
        return None
    path = Path(cover_path)
    if not path.exists():
        return None
    try:
        with PILImage.open(path) as im:
            width_px, height_px = im.size
    except Exception:
        return None
    if not width_px or not height_px:
        return None
    ratio = min(max_width / width_px, max_height / height_px, 1.0)
    image = Image(str(path), width=width_px * ratio, height=height_px * ratio)
    image.hAlign = "LEFT"
    return image


def _label_value_table(rows, styles, page_width, label_ratio=0.42):
    """Таблица label/значение в две колонки — форма, общая у «Паспорта
    объекта», «Паспорта договора» и «Расчётных коэффициентов».

    ``label`` — всегда подпись поля из фиксированного словаря labels; сам
    экран экранировать не нужно. ``value`` — со стороны данных: то, что
    человек вписал или программа извлекла из документа, и оно экранируется
    здесь одним местом на все три вызывающих блока.
    """
    label_w = min(230.0, page_width * label_ratio)
    value_w = page_width - label_w
    data = [
        [Paragraph(label, styles["cell_label"]), Paragraph(_esc(value), styles["cell"])]
        for label, value in rows
    ]
    table = Table(data, colWidths=[label_w, value_w])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _project_facts_block(passport, fields, field_labels, numeric_fields,
                         format_number, price_per_sqm, styles, page_width):
    rows = []
    for field in fields:
        if field == "project_name":
            continue
        value = passport.get(field)
        if value is None:
            text = "—"
        elif field in numeric_fields:
            text = format_number(value)
        else:
            text = str(value)
        rows.append((field_labels.get(field, field), text))
        if field == "contract_price_rub":
            psqm = price_per_sqm(passport)
            rows.append((
                "Цена за м², руб.",
                format_number(psqm) if psqm is not None else "—",
            ))
    return [
        Paragraph("Паспорт объекта", styles["heading"]),
        _label_value_table(rows, styles, page_width),
    ]


def _project_terms_block(passport, has_contract_terms, contract_fields,
                         contract_field_labels, styles, page_width):
    if not has_contract_terms:
        return []
    rows = [
        (contract_field_labels.get(field, field), passport.get(field) or "—")
        for field in contract_fields
    ]
    return [
        Paragraph("Паспорт договора", styles["heading"]),
        _label_value_table(rows, styles, page_width),
    ]


def _project_coefficients_block(
    has_estimate, concrete_volume, concrete_coefficient,
    facade_area, facade_coefficient, rebar_coefficient,
    format_number, styles, page_width,
):
    rows = []
    if has_estimate and concrete_volume is not None:
        rows.append(("Объём монолита по смете, м³", format_number(concrete_volume)))
        rows.append((
            "Коэффициент монолита за общую площадь по СП, м³/м²",
            format_number(concrete_coefficient) if concrete_coefficient is not None else "—",
        ))
    rows.append((
        "Коэффициент арматуры (средний), кг/м³",
        format_number(rebar_coefficient) if rebar_coefficient is not None else "—",
    ))
    rows.append((
        "Площадь фасада по смете, м²",
        format_number(facade_area) if facade_area is not None else "—",
    ))
    rows.append((
        "Коэффициент фасада за общую площадь по СП, м²(фас)/м²",
        format_number(facade_coefficient) if facade_coefficient is not None else "—",
    ))
    return [
        Paragraph("Расчётные коэффициенты бетонных и фасадных конструкций", styles["heading"]),
        _label_value_table(rows, styles, page_width),
    ]


def _project_increase_block(report, format_number, format_percent, format_delta,
                            styles, page_width):
    """«Удорожание объекта» — тот же отчёт по видам работ, что на странице
    проекта. Не смета: это её отдельный посчитанный результат, и в справку
    он входит, даже когда саму смету туда класть не нужно."""
    if not report:
        return []

    if report.from_estimate:
        note = (
            'Удорожание считается от сметы: столбец «стало» против стоимости '
            'раздела в смете. К «было» программа обращается только там, где '
            '«стало» пустое.'
        )
        baseline_header = "Смета, руб."
    else:
        note = (
            'Смета не загружена, поэтому удорожание считается от столбца '
            '«было» самого файла.'
        )
        baseline_header = "Было, руб."

    # Built up in block, not story directly, and wrapped in KeepTogether
    # below: without it the heading could be the last thing that fits at
    # the bottom of a page, with the table itself starting fresh on the
    # next one.
    block = [
        Paragraph("Удорожание объекта", styles["heading"]),
        Paragraph(note, styles["sub"]),
    ]

    label_w = min(150.0, page_width * 0.3)
    columns = 4
    rest = max(page_width - label_w, 200.0) / columns
    head = [
        Paragraph("Вид работ", styles["head"]),
        Paragraph(baseline_header, styles["head"]),
        Paragraph("Стало, руб.", styles["head"]),
        Paragraph("Удорожание, руб.", styles["head"]),
        Paragraph("Удорожание, %", styles["head"]),
    ]
    data = [head]
    for row in report.rows:
        colour = RED if row.delta > 0 else (ACCENT if row.delta < 0 else MUTED)
        current_text = format_number(row.current)
        if row.source == "was":
            current_text += f' <font size="6" color="{_hex(AMBER)}">— в «стало» пусто, взято «было»</font>'
        elif row.source == "none":
            current_text += f' <font size="6" color="{_hex(AMBER)}">— в файле нет данных</font>'
        percent_text = format_percent(row.percent) if row.percent is not None else "новые работы"
        data.append([
            Paragraph(_esc(row.label), styles["cell"]),
            Paragraph(format_number(row.baseline), styles["cell_right"]),
            Paragraph(current_text, styles["cell_right"]),
            Paragraph(
                f'<font color="{_hex(colour)}">{format_delta(row.delta)}</font>',
                styles["cell_right"],
            ),
            Paragraph(
                f'<font color="{_hex(colour)}">{percent_text}</font>',
                styles["cell_right"],
            ),
        ])

    total = report.total
    total_colour = RED if total.delta > 0 else (ACCENT if total.delta < 0 else MUTED)
    data.append([
        Paragraph(total.label, styles["cell_label"]),
        Paragraph(format_number(total.baseline), styles["cell_right"]),
        Paragraph(format_number(total.current), styles["cell_right"]),
        Paragraph(
            f'<font color="{_hex(total_colour)}">{format_delta(total.delta)}</font>',
            styles["cell_right"],
        ),
        Paragraph(
            f'<font color="{_hex(total_colour)}">{format_percent(total.percent) or "—"}</font>',
            styles["cell_right"],
        ),
    ])

    table = Table(data, colWidths=[label_w] + [rest] * columns, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("BACKGROUND", (0, -1), (-1, -1), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    block.append(table)
    story = [KeepTogether(block)]

    if report.unmatched:
        names = "; ".join(_esc(name) for name in report.unmatched)
        story.append(Paragraph(
            'Строки файла, для которых в отчёте нет вида работ, в таблицу не '
            f'попали: {names}.',
            styles["sub"],
        ))
    return story


def build_project_pdf(
    passport: dict, fields: list, field_labels: dict, numeric_fields=(),
    format_number=str, price_per_sqm=lambda data: None,
    has_contract_terms=False, contract_fields=(), contract_field_labels=None,
    cover_path=None,
    has_estimate=False, concrete_volume=None, concrete_coefficient=None,
    facade_area=None, facade_coefficient=None,
    cost_increase_report=None, format_percent=None, format_delta=None,
) -> bytes:
    """Справка по одному объекту — паспорт, договор, коэффициенты и
    удорожание, картинкой и одним файлом. Смета в неё не входит: кто хочет
    сверить со сметой, откроет её отдельно — здесь только то, что нужно,
    чтобы сослаться на объект, не заходя в приложение.
    """
    _ensure_fonts()
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=PROJECT_PAGE_SIZE, title=passport.get("project_name") or "Справка по объекту",
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
    )
    page_width = PROJECT_PAGE_SIZE[0] - doc.leftMargin - doc.rightMargin

    story = [Paragraph(_esc(passport.get("project_name")) or "Справка по объекту", styles["title"])]
    cover = _project_cover_image(cover_path, min(260.0, page_width), 180.0)
    if cover is not None:
        story.append(cover)
        story.append(Spacer(1, 8))
    if passport.get("address"):
        story.append(Paragraph(_esc(passport["address"]), styles["sub"]))

    story += _project_facts_block(
        passport, fields, field_labels, numeric_fields,
        format_number, price_per_sqm, styles, page_width,
    )
    story += _project_terms_block(
        passport, has_contract_terms, contract_fields, contract_field_labels or {},
        styles, page_width,
    )
    story += _project_coefficients_block(
        has_estimate, concrete_volume, concrete_coefficient,
        facade_area, facade_coefficient, passport.get("rebar_coefficient_avg"),
        format_number, styles, page_width,
    )
    story += _project_increase_block(
        cost_increase_report, format_number, format_percent, format_delta,
        styles, page_width,
    )

    doc.build(story, onFirstPage=_draw_logo, onLaterPages=_draw_logo)
    return buffer.getvalue()
