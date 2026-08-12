# Просмотр сметы (.xlsx) в проекте — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At project creation, let the user optionally attach an estimate
(`смета`) as an `.xlsx` file, and view it in the browser as a formatted
table — no download, no Excel required.

**Architecture:** A new `app/estimate.py` module parses an `.xlsx` file with
`openpyxl` into a plain data structure (sheets → rows → cells, with basic
formatting), which a new Jinja template renders as HTML tables with tab
navigation between sheets. The file is stored alongside the existing
`dgp.docx`/`tz.docx` uploads at `raw/smeta.xlsx` and validated the same way
they are — before the project directory is considered created.

**Tech Stack:** Flask, Jinja2, `openpyxl` (new dependency), pytest.

## Global Constraints

- Only `.xlsx` is supported (no legacy binary `.xls`).
- The estimate upload is optional — a project can be created without one.
- Charts, embedded images, and complex/conditional formatting inside the
  workbook are not rendered — only cell values plus: bold, italic,
  background fill color, horizontal alignment, per-side borders, merged
  cells, and relative column widths.
- Formula cells render their cached computed value (never the raw
  `=...` formula text); if no cached value is present, render blank.
- No re-upload/replace of the estimate after project creation.
- No extraction of estimate data into the passport.

Spec: `docs/superpowers/specs/2026-08-12-estimate-xlsx-view-design.md`

---

### Task 1: `app/estimate.py` — parse and render an .xlsx workbook

**Files:**
- Create: `app/estimate.py`
- Modify: `requirements.txt`
- Test: `tests/test_estimate.py`

**Interfaces:**
- Produces: `estimate.read_estimate(path) -> list[dict]`, where each dict is
  `{"name": str, "rows": list[list[dict]], "col_widths": list[float]}` and
  each cell dict is `{"value": str, "rowspan": int, "colspan": int,
  "bold": bool, "italic": bool, "align": str|None, "bg": str|None,
  "border_top": bool, "border_right": bool, "border_bottom": bool,
  "border_left": bool}`.
- Produces: `estimate.EstimateReadError(Exception)`, raised when the file
  can't be opened as a workbook (wrong format, corrupted).
- Consumes: `passport.format_number(value)` (already exists in
  `app/passport.py`) for consistent thousands-space number formatting.

- [ ] **Step 1: Add the `openpyxl` dependency**

Edit `requirements.txt`, add a line after `Pillow`:

```
openpyxl>=3.1,<4.0
```

Install it into the dev environment:

```bash
pip install -r requirements-dev.txt
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_estimate.py`:

```python
import pytest
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from app import estimate


def _save(tmp_path, wb, filename="smeta.xlsx"):
    path = tmp_path / filename
    wb.save(path)
    return path


def test_read_estimate_simple_values(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Раздел", "Кол-во", "Цена"])
    ws.append(["Земляные работы", 10, 1500.5])
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)

    assert len(sheets) == 1
    rows = sheets[0]["rows"]
    assert [c["value"] for c in rows[0]] == ["Раздел", "Кол-во", "Цена"]
    assert [c["value"] for c in rows[1]] == ["Земляные работы", "10", "1 500.50"]


def test_read_estimate_merged_cells_collapse_into_one(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Заголовок"
    ws.merge_cells("A1:C1")
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)

    row = sheets[0]["rows"][0]
    assert len(row) == 1
    assert row[0]["value"] == "Заголовок"
    assert row[0]["colspan"] == 3
    assert row[0]["rowspan"] == 1


def test_read_estimate_multiple_sheets_in_order(tmp_path):
    wb = Workbook()
    wb.active.title = "Смета"
    wb.create_sheet("Материалы")
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)

    assert [s["name"] for s in sheets] == ["Смета", "Материалы"]


def test_read_estimate_skips_hidden_sheet(tmp_path):
    wb = Workbook()
    wb.active.title = "Видимый"
    hidden = wb.create_sheet("Скрытый")
    hidden.sheet_state = "hidden"
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)

    assert [s["name"] for s in sheets] == ["Видимый"]


def test_read_estimate_formula_cell_never_shows_raw_formula_text(tmp_path):
    """openpyxl never evaluates formulas — a workbook it just created has no
    cached value for a formula cell, so it must render blank rather than
    leaking the raw "=..." text. (A real Excel-saved file *does* carry a
    cached value, which openpyxl's own data_only mode is trusted to read —
    that part isn't ours to re-test.)"""
    wb = Workbook()
    ws = wb.active
    ws["A1"] = 10
    ws["A2"] = "=A1*2"
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)

    assert sheets[0]["rows"][1][0]["value"] == ""


def test_read_estimate_captures_basic_formatting(tmp_path):
    wb = Workbook()
    ws = wb.active
    cell = ws["A1"]
    cell.value = "Итого"
    cell.font = Font(bold=True, italic=True)
    cell.fill = PatternFill(fill_type="solid", fgColor="FFFF0000")
    cell.alignment = Alignment(horizontal="center")
    cell.border = Border(top=Side(style="thin"), bottom=Side(style="thin"))
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)
    rendered = sheets[0]["rows"][0][0]

    assert rendered["value"] == "Итого"
    assert rendered["bold"] is True
    assert rendered["italic"] is True
    assert rendered["bg"] == "#FF0000"
    assert rendered["align"] == "center"
    assert rendered["border_top"] is True
    assert rendered["border_bottom"] is True
    assert rendered["border_left"] is False


def test_read_estimate_reports_column_widths(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "x"
    ws["B1"] = "y"
    ws.column_dimensions["B"].width = 40
    path = _save(tmp_path, wb)

    sheets = estimate.read_estimate(path)
    widths = sheets[0]["col_widths"]

    assert len(widths) == 2
    assert widths[1] == 40


def test_read_estimate_raises_on_corrupted_file(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not a real xlsx file")

    with pytest.raises(estimate.EstimateReadError):
        estimate.read_estimate(path)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_estimate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.estimate'`
(or `ImportError`) — the module doesn't exist yet.

- [ ] **Step 4: Implement `app/estimate.py`**

Create `app/estimate.py`:

```python
import zipfile
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

from .passport import format_number

DEFAULT_COLUMN_WIDTH = 8.43  # Excel's own default column width, in characters.
_ALIGNMENT_MAP = {
    "left": "left",
    "right": "right",
    "center": "center",
    "centerContinuous": "center",
}


class EstimateReadError(Exception):
    pass


def read_estimate(path) -> list:
    """Parse an .xlsx workbook into a list of rendered sheets.

    Each sheet is ``{"name": str, "rows": [[cell, ...], ...], "col_widths":
    [float, ...]}``. Hidden and very-hidden sheets are skipped. A cell
    covered by a merge (other than the merge's top-left cell) is omitted
    from its row — the top-left cell instead carries the merge's rowspan
    and colspan.
    """
    path = Path(path)
    try:
        wb_styles = openpyxl.load_workbook(path, data_only=False)
        wb_values = openpyxl.load_workbook(path, data_only=True)
    except (zipfile.BadZipFile, KeyError, InvalidFileException, ValueError) as e:
        raise EstimateReadError(f"Cannot read {path}: {e}") from e

    sheets = []
    for ws_styles in wb_styles.worksheets:
        if ws_styles.sheet_state != "visible":
            continue
        sheets.append(_render_sheet(ws_styles, wb_values[ws_styles.title]))
    return sheets


def _render_sheet(ws_styles, ws_values):
    max_row = ws_styles.max_row or 0
    max_col = ws_styles.max_column or 0
    span, covered = _merge_spans(ws_styles)

    rows = []
    for r in range(1, max_row + 1):
        row_cells = []
        for c in range(1, max_col + 1):
            if (r, c) in covered:
                continue
            rowspan, colspan = span.get((r, c), (1, 1))
            row_cells.append(_render_cell(
                ws_styles.cell(row=r, column=c),
                ws_values.cell(row=r, column=c),
                rowspan, colspan,
            ))
        rows.append(row_cells)

    col_widths = []
    for c in range(1, max_col + 1):
        dim = ws_styles.column_dimensions.get(get_column_letter(c))
        col_widths.append(dim.width if dim and dim.width else DEFAULT_COLUMN_WIDTH)

    return {"name": ws_styles.title, "rows": rows, "col_widths": col_widths}


def _merge_spans(ws):
    """(span, covered): ``span`` maps a merge's top-left ``(row, col)`` to
    ``(rowspan, colspan)``; ``covered`` holds every other ``(row, col)``
    inside a merged range, which must be skipped when laying out a row."""
    span = {}
    covered = set()
    for merged_range in ws.merged_cells.ranges:
        top_left = (merged_range.min_row, merged_range.min_col)
        span[top_left] = (
            merged_range.max_row - merged_range.min_row + 1,
            merged_range.max_col - merged_range.min_col + 1,
        )
        for r in range(merged_range.min_row, merged_range.max_row + 1):
            for c in range(merged_range.min_col, merged_range.max_col + 1):
                if (r, c) != top_left:
                    covered.add((r, c))
    return span, covered


def _render_cell(cell_style, cell_value, rowspan, colspan):
    border = cell_style.border
    return {
        "value": _format_value(cell_value.value),
        "rowspan": rowspan,
        "colspan": colspan,
        "bold": bool(cell_style.font and cell_style.font.bold),
        "italic": bool(cell_style.font and cell_style.font.italic),
        "align": _alignment(cell_style.alignment),
        "bg": _fill_color(cell_style.fill),
        "border_top": _has_border(border.top),
        "border_right": _has_border(border.right),
        "border_bottom": _has_border(border.bottom),
        "border_left": _has_border(border.left),
    }


def _format_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, (int, float)):
        return format_number(value)
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y")
    return str(value)


def _alignment(alignment):
    if alignment is None or not alignment.horizontal:
        return None
    return _ALIGNMENT_MAP.get(alignment.horizontal)


def _fill_color(fill):
    if fill is None or fill.fill_type != "solid":
        return None
    fg = fill.fgColor
    if fg is None or fg.type != "rgb" or not fg.rgb:
        return None
    rgb = fg.rgb
    if not isinstance(rgb, str) or len(rgb) < 6:
        return None
    if len(rgb) == 8:  # AARRGGBB -> drop the alpha channel
        rgb = rgb[2:]
    return f"#{rgb}"


def _has_border(side):
    return bool(side and side.style)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_estimate.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt app/estimate.py tests/test_estimate.py
git commit -m "feat: parse and render .xlsx estimate workbooks"
```

---

### Task 2: Upload, storage, and the `/smeta` route

**Files:**
- Modify: `app/storage.py`
- Modify: `app/routes.py`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `estimate.read_estimate(path)` / `estimate.EstimateReadError`
  (Task 1).
- Produces: `storage.estimate_path(root, slug) -> Path` — the fixed
  location `raw/smeta.xlsx`, used by both the route and the template
  condition for showing the "Смета" link.
- Produces: route `GET /projects/<slug>/smeta` (view name
  `main.estimate_page`), and a `has_estimate: bool` context variable on
  `main.project_page`'s template render — Task 3's template consumes both.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_routes.py`. First add this import at the top of the
file, alongside the existing `import io`:

```python
from openpyxl import Workbook
```

Then add near `_tz_bytes()`:

```python
def _smeta_bytes():
    wb = Workbook()
    wb.active.append(["Раздел", "Сумма"])
    wb.active.append(["Фундамент", 1000])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

Then add these test functions anywhere in the file:

```python
def test_create_project_with_estimate_saves_and_serves_it(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Со сметой",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(_smeta_bytes()), "smeta.xlsx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 302
    slug = "Со_сметой"

    from app import storage
    assert storage.estimate_path(tmp_path, slug).exists()

    page = client.get(f"/projects/{slug}/smeta")
    assert page.status_code == 200
    assert "Фундамент".encode("utf-8") in page.data


def test_create_project_without_estimate_smeta_route_404s(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Без сметы",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 302
    slug = "Без_сметы"

    page = client.get(f"/projects/{slug}/smeta")
    assert page.status_code == 404


def test_create_project_rejects_non_xlsx_estimate(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Плохая смета",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(b"not excel"), "smeta.txt"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400

    from app import storage
    assert storage.list_project_slugs(tmp_path) == []


def test_create_project_rejects_corrupted_estimate(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Битая смета",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(b"this is not a real xlsx file"), "smeta.xlsx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400

    from app import storage
    assert storage.list_project_slugs(tmp_path) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_routes.py -k estimate -v`
Expected: FAIL — `AttributeError: module 'app.storage' has no attribute
'estimate_path'` (or a 404/500 on `/projects` since `smeta_file` isn't
handled yet).

- [ ] **Step 3: Add `storage.estimate_path`**

In `app/storage.py`, add this function right after `passport_path`
(currently lines 43-44):

```python
def estimate_path(root: Path, slug: str) -> Path:
    return raw_dir(root, slug) / "smeta.xlsx"
```

- [ ] **Step 4: Wire the upload, validation, and view route into `app/routes.py`**

Change the import line at the top of `app/routes.py`:

```python
from . import estimate, extractors, passport as passport_module, pdf_export, storage
```

Add the new extension constant right after `ALLOWED_EXTENSION`:

```python
ALLOWED_EXTENSION = ".docx"
ALLOWED_ESTIMATE_EXTENSION = ".xlsx"
```

Replace the whole `create_project` function with:

```python
@bp.route("/projects", methods=["POST"])
def create_project():
    root = _projects_root()
    project_name = request.form.get("project_name", "").strip()
    dgp_file = request.files.get("dgp_file")
    tz_file = request.files.get("tz_file")
    smeta_file = request.files.get("smeta_file")

    if not project_name:
        return render_template("new_project.html", error="Введите название проекта"), 400
    if not dgp_file or not dgp_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл Договора в формате .docx"), 400
    if not tz_file or not tz_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл ТЗ в формате .docx"), 400
    has_smeta = bool(smeta_file and smeta_file.filename)
    if has_smeta and not smeta_file.filename.lower().endswith(ALLOWED_ESTIMATE_EXTENSION):
        return render_template("new_project.html", error="Смета должна быть в формате .xlsx"), 400

    try:
        slug = storage.create_project(root, project_name)
    except ValueError:
        # The name is non-empty but consists only of characters slugify
        # strips (e.g. "***"), so there is no usable folder name for it.
        return render_template(
            "new_project.html",
            error="Название проекта должно содержать хотя бы одну букву или цифру",
        ), 400

    raw = storage.raw_dir(root, slug)
    dgp_path = raw / "dgp.docx"
    tz_path = raw / "tz.docx"
    dgp_file.save(dgp_path)
    tz_file.save(tz_path)

    if has_smeta:
        smeta_path = storage.estimate_path(root, slug)
        smeta_file.save(smeta_path)
        try:
            estimate.read_estimate(smeta_path)
        except estimate.EstimateReadError as e:
            current_app.logger.warning("Не удалось разобрать смету: %s", e)
            shutil.rmtree(storage.project_dir(root, slug), ignore_errors=True)
            return render_template(
                "new_project.html",
                error="Не удалось прочитать смету — убедитесь, что это корректный файл .xlsx",
            ), 400

    try:
        data = passport_module.build_passport(project_name, dgp_path, tz_path)
    except DocxReadError as e:
        # Don't let a cleanup failure (file lock, permissions) turn the
        # intended 400 into a 500 — the orphan directory is harmless anyway,
        # storage.list_project_slugs ignores directories without a passport.
        current_app.logger.warning("Не удалось разобрать загруженный файл: %s", e)
        shutil.rmtree(storage.project_dir(root, slug), ignore_errors=True)
        return render_template(
            "new_project.html",
            error="Не удалось прочитать файл — убедитесь, что это корректный .docx",
        ), 400

    passport_module.save_passport(data, storage.passport_path(root, slug))
    return redirect(url_for("main.project_page", slug=slug))
```

Add `has_estimate` to the `project_page` render call — change:

```python
    return render_template(
        "project.html",
        slug=slug,
        passport=data,
        fields=passport_module.PASSPORT_FIELDS,
        field_labels=passport_module.FIELD_LABELS,
        ocr_fields=data.get("ocr_fields", []),
        price_per_sqm=passport_module.price_per_sqm(data),
        building_class_options=passport_module.BUILDING_CLASS_OPTIONS,
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
    )
```

to:

```python
    return render_template(
        "project.html",
        slug=slug,
        passport=data,
        fields=passport_module.PASSPORT_FIELDS,
        field_labels=passport_module.FIELD_LABELS,
        ocr_fields=data.get("ocr_fields", []),
        price_per_sqm=passport_module.price_per_sqm(data),
        building_class_options=passport_module.BUILDING_CLASS_OPTIONS,
        numeric_fields=passport_module.NUMERIC_FIELDS,
        format_number=passport_module.format_number,
        has_estimate=storage.estimate_path(root, slug).exists(),
    )
```

Add the new route — put it right after `project_page`, before
`delete_project`:

```python
@bp.route("/projects/<slug>/smeta", methods=["GET"])
def estimate_page(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.estimate_path(root, slug)
    if not path.exists():
        abort(404)
    sheets = estimate.read_estimate(path)
    project_name = passport_module.load_passport(storage.passport_path(root, slug)).get("project_name") or slug
    return render_template("estimate.html", slug=slug, project_name=project_name, sheets=sheets)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_routes.py -k estimate -v`
Expected: PASS (4 tests). Note: `test_create_project_with_estimate_saves_and_serves_it`
will only fully pass once Task 3 adds `estimate.html` — if it fails on a
`TemplateNotFound` error at this point, that's expected; re-run it after
Task 3.

- [ ] **Step 6: Run the full test suite to check nothing else broke**

Run: `pytest -v`
Expected: all previously-passing tests still PASS; the two new-route
tests that need `estimate.html` may still fail here — that's fine, they
get fixed in Task 3.

- [ ] **Step 7: Commit**

```bash
git add app/storage.py app/routes.py tests/test_routes.py
git commit -m "feat: upload, validate, and serve the estimate file"
```

---

### Task 3: Templates and styling

**Files:**
- Modify: `app/templates/base.html`
- Modify: `app/templates/new_project.html`
- Modify: `app/templates/project.html`
- Create: `app/templates/estimate.html`
- Modify: `app/static/style.css`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `has_estimate` (project page context), `estimate.read_estimate`'s
  sheet/cell dicts (Task 1), route `main.estimate_page` (Task 2).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_routes.py`:

```python
def test_new_project_form_has_optional_estimate_field(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()

    resp = client.get("/projects/new")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'name="smeta_file"' in body
    assert 'accept=".xlsx"' in body


def test_project_page_shows_estimate_link_when_file_present(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    client.post("/projects", data={
        "project_name": "Есть смета",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(_smeta_bytes()), "smeta.xlsx"),
    }, content_type="multipart/form-data")

    page = client.get("/projects/Есть_смета")

    assert page.status_code == 200
    assert 'href="/projects/Есть_смета/smeta"'.encode("utf-8") in page.data


def test_project_page_hides_estimate_link_when_no_file(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    client.post("/projects", data={
        "project_name": "Нет сметы",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")

    page = client.get("/projects/Нет_сметы")

    assert page.status_code == 200
    assert b"/smeta" not in page.data


def test_estimate_page_renders_multiple_sheets_as_tabs(tmp_path):
    wb = Workbook()
    wb.active.title = "Смета"
    wb.active["A1"] = "Итого"
    wb.create_sheet("Материалы")["A1"] = "Цемент"
    buf = io.BytesIO()
    wb.save(buf)

    app = create_app(tmp_path)
    client = app.test_client()
    client.post("/projects", data={
        "project_name": "Многолистовая",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(buf.getvalue()), "smeta.xlsx"),
    }, content_type="multipart/form-data")

    page = client.get("/projects/Многолистовая/smeta")

    assert page.status_code == 200
    body = page.data.decode("utf-8")
    assert "Итого" in body
    assert "Цемент" in body
    assert "Материалы" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_routes.py -k "estimate_field or estimate_link or estimate_page" -v`
Expected: FAIL — missing form field / link / `TemplateNotFound:
estimate.html`.

- [ ] **Step 3: Let the base template take an extra body class**

In `app/templates/base.html`, change:

```html
  <main class="container">
```

to:

```html
  <main class="container {% block main_extra_class %}{% endblock %}">
```

- [ ] **Step 4: Add the estimate field to the new-project form**

In `app/templates/new_project.html`, insert this block right before the
`<button type="submit" ...>` line:

```html
    <div class="field">
      <label for="smeta_file">Смета (необязательно), .xlsx</label>
      <label class="file-drop" for="smeta_file">
        <svg class="file-drop-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 16V4M12 4l-4 4M12 4l4 4"/>
          <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>
        </svg>
        <span class="file-drop-text" data-placeholder="Выберите файл .xlsx">Выберите файл .xlsx</span>
      </label>
      <input class="file-input" type="file" id="smeta_file" name="smeta_file" accept=".xlsx">
    </div>
```

The existing script at the bottom of the file already wires up every
element with class `.file-input` generically, so no JS changes are needed
here.

- [ ] **Step 5: Add the "Смета" link to the project page**

In `app/templates/project.html`, change the `page-head` block from:

```html
<div class="page-head">
  <div>
    <a class="back-link" href="{{ url_for('main.index') }}">&larr; Все проекты</a>
    <h1>{{ passport.project_name }}</h1>
    <p class="page-sub">
      Синий — распознано с картинки, стоит проверить. Жёлтый — заполните вручную.
    </p>
  </div>
</div>
```

to:

```html
<div class="page-head">
  <div>
    <a class="back-link" href="{{ url_for('main.index') }}">&larr; Все проекты</a>
    <h1>{{ passport.project_name }}</h1>
    <p class="page-sub">
      Синий — распознано с картинки, стоит проверить. Жёлтый — заполните вручную.
    </p>
  </div>
  {% if has_estimate %}
  <div class="page-head-actions">
    <a class="btn btn-secondary" href="{{ url_for('main.estimate_page', slug=slug) }}">Смета</a>
  </div>
  {% endif %}
</div>
```

- [ ] **Step 6: Create the estimate view template**

Create `app/templates/estimate.html`:

```html
{% extends "base.html" %}
{% block main_extra_class %}container-wide{% endblock %}
{% block content %}
<div class="page-head">
  <div>
    <a class="back-link" href="{{ url_for('main.project_page', slug=slug) }}">&larr; {{ project_name }}</a>
    <h1>Смета</h1>
  </div>
</div>

{% if sheets|length > 1 %}
<div class="sheet-tabs">
  {% for sheet in sheets %}
  <button type="button" class="sheet-tab {{ 'is-active' if loop.first else '' }}" data-sheet-index="{{ loop.index0 }}">{{ sheet.name }}</button>
  {% endfor %}
</div>
{% endif %}

{% for sheet in sheets %}
<div class="sheet-panel {{ 'is-active' if loop.first else '' }}" data-sheet-index="{{ loop.index0 }}">
  <div class="estimate-table-wrap">
    <table class="estimate-table">
      <colgroup>
        {% for width in sheet.col_widths %}
        <col style="width: {{ width }}ch">
        {% endfor %}
      </colgroup>
      <tbody>
        {% for row in sheet.rows %}
        <tr>
          {% for cell in row %}
          <td
            {% if cell.rowspan > 1 %}rowspan="{{ cell.rowspan }}"{% endif %}
            {% if cell.colspan > 1 %}colspan="{{ cell.colspan }}"{% endif %}
            class="{{ 'is-bold' if cell.bold else '' }} {{ 'is-italic' if cell.italic else '' }} {{ 'align-' + cell.align if cell.align else '' }} {{ 'border-t' if cell.border_top else '' }} {{ 'border-r' if cell.border_right else '' }} {{ 'border-b' if cell.border_bottom else '' }} {{ 'border-l' if cell.border_left else '' }}"
            {% if cell.bg %}style="background-color: {{ cell.bg }}"{% endif %}
          >{{ cell.value }}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endfor %}

<script>
  document.querySelectorAll('.sheet-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      var index = tab.dataset.sheetIndex;
      document.querySelectorAll('.sheet-tab').forEach(function (t) {
        t.classList.toggle('is-active', t === tab);
      });
      document.querySelectorAll('.sheet-panel').forEach(function (panel) {
        panel.classList.toggle('is-active', panel.dataset.sheetIndex === index);
      });
    });
  });
</script>
{% endblock %}
```

- [ ] **Step 7: Add the estimate table styles**

Append to `app/static/style.css`:

```css
/* Estimate view */

.container-wide {
  max-width: 1400px;
}

.sheet-tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.sheet-tab {
  padding: 8px 14px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--white);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-500);
}

.sheet-tab.is-active {
  background: var(--green-700);
  color: var(--white);
  border-color: var(--green-700);
}

.sheet-panel {
  display: none;
}

.sheet-panel.is-active {
  display: block;
}

.estimate-table-wrap {
  overflow-x: auto;
  background: var(--white);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

.estimate-table {
  border-collapse: collapse;
  font-size: 13px;
  white-space: nowrap;
}

.estimate-table td {
  padding: 5px 10px;
  border: 1px solid transparent;
}

.estimate-table td.is-bold {
  font-weight: 700;
}

.estimate-table td.is-italic {
  font-style: italic;
}

.estimate-table td.align-left {
  text-align: left;
}

.estimate-table td.align-center {
  text-align: center;
}

.estimate-table td.align-right {
  text-align: right;
}

.estimate-table td.border-t {
  border-top-color: var(--border);
}

.estimate-table td.border-r {
  border-right-color: var(--border);
}

.estimate-table td.border-b {
  border-bottom-color: var(--border);
}

.estimate-table td.border-l {
  border-left-color: var(--border);
}
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `pytest tests/test_routes.py -v`
Expected: PASS — every test in the file, including the ones added in
Task 2 and Task 3.

- [ ] **Step 9: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS.

- [ ] **Step 10: Manual smoke test**

```bash
python run.py
```

Open `http://127.0.0.1:5000/projects/new`, create a project attaching a
real multi-sheet `.xlsx` estimate with some merged header cells and a
colored row. Open the project page, click "Смета", confirm: sheet tabs
switch correctly, merged cells span the right width, and formatting
(bold/colors/borders) roughly matches the original file.

- [ ] **Step 11: Commit**

```bash
git add app/templates/base.html app/templates/new_project.html app/templates/project.html app/templates/estimate.html app/static/style.css tests/test_routes.py
git commit -m "feat: view the uploaded estimate as a formatted table in the browser"
```
