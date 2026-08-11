from io import BytesIO
from pathlib import Path

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

# ReportLab's built-in fonts only cover Latin-1 — every label here is
# Russian, so a system Cyrillic-capable TTF must be registered before any
# text is drawn, or Cyrillic characters render as blank boxes.
_FONT_DIR = Path(r"C:\Windows\Fonts")
_FONTS_REGISTERED = False
ACCENT_COLOR = colors.HexColor("#1f6b4c")

CHART_DEFS = [
    ("price_by_year", "Цена работ по году подписания договора"),
    ("price_by_class", "Цена работ по классу жилья"),
    ("price", "Цена работ по проектам"),
    ("price_per_sqm", "Цена за м² по проектам"),
]


def _ensure_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont("Arial", str(_FONT_DIR / "arial.ttf")))
    pdfmetrics.registerFont(TTFont("Arial-Bold", str(_FONT_DIR / "arialbd.ttf")))
    _FONTS_REGISTERED = True


def _chart_drawing(rows, width):
    height = 28 * len(rows) + 30
    drawing = Drawing(width, height)
    chart = HorizontalBarChart()
    chart.x = 170
    chart.y = 10
    chart.width = width - 210
    chart.height = height - 20
    chart.data = [[row["value"] for row in rows]]
    chart.categoryAxis.categoryNames = [row["label"] for row in rows]
    chart.categoryAxis.labels.fontName = "Arial"
    chart.categoryAxis.labels.fontSize = 8
    chart.valueAxis.labels.fontName = "Arial"
    chart.valueAxis.labels.fontSize = 8
    chart.valueAxis.valueMin = 0
    chart.bars[0].fillColor = ACCENT_COLOR
    drawing.add(chart)
    return drawing


def build_compare_pdf(passports: dict, slugs: list, fields: list, field_labels: dict, charts: dict) -> bytes:
    _ensure_fonts()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title="Сравнение проектов",
        leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36,
    )

    title_style = ParagraphStyle("Title", fontName="Arial-Bold", fontSize=18, spaceAfter=16)
    heading_style = ParagraphStyle("Heading", fontName="Arial-Bold", fontSize=13, spaceBefore=18, spaceAfter=8)
    body_style = ParagraphStyle("Body", fontName="Arial", fontSize=10)

    page_width = A4[0] - doc.leftMargin - doc.rightMargin
    story = [Paragraph("Сравнение проектов", title_style)]

    for key, title in CHART_DEFS:
        rows = charts.get(key) or []
        story.append(Paragraph(title, heading_style))
        if rows:
            story.append(_chart_drawing(rows, page_width))
        else:
            story.append(Paragraph("Недостаточно данных для этого графика.", body_style))

    story.append(Paragraph("Таблица сравнения", heading_style))
    header = [""] + [passports[slug].get("project_name") or slug for slug in slugs]
    table_data = [header]
    for field in fields:
        if field == "project_name":
            continue
        row = [field_labels.get(field, field)]
        for slug in slugs:
            value = passports[slug].get(field)
            row.append(str(value) if value is not None else "—")
        table_data.append(row)

    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Arial"),
        ("FONTNAME", (0, 0), (-1, 0), "Arial-Bold"),
        ("FONTNAME", (0, 0), (0, -1), "Arial-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e3e8e5")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f8f4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(table)

    doc.build(story)
    return buffer.getvalue()
