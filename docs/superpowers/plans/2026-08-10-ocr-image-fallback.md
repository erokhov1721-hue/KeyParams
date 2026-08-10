# Резервное распознавание полей с картинок в .docx — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Когда поле паспорта объекта не находится в обычном тексте/таблицах
.docx, программа распознаёт текст на картинках, встроенных в загруженные
файлы (OCR), и повторяет тот же поиск по распознанному тексту — заполняя
поле автоматически, но с отдельной отметкой "с картинки, проверьте".

**Architecture:** `document_reader.py` дополнительно достаёт байты всех
растровых картинок из архива .docx (`DocxContent.images`). Новый модуль
`app/ocr.py` — единственная точка входа в Tesseract OCR, никогда не бросает
исключений. `passport.py` считает поля как раньше и, только если что-то
осталось `None`, лениво распознаёт нужные картинки и повторяет те же самые
функции поиска из `extractors.py` (для текстовых полей — через временный
`DocxContent`, для трёх площадей — через новую функцию для плоского текста).
Список полей, заполненных из OCR, сохраняется в `passport.json` как
`ocr_fields` и показывается в интерфейсе отдельным значком.

**Tech Stack:** Python 3, Flask (без изменений), Tesseract OCR (системная
программа, локально) + `pytesseract` + `Pillow` (новые зависимости), pytest.

## Global Constraints

- Никаких внешних облачных LLM/API — распознавание текста с картинок тоже
  выполняется полностью локально (Tesseract OCR, без интернета в рантайме).
- Заполнение полей — автоматическое, без запроса подтверждения; поле,
  заполненное через OCR, дополнительно помечается в интерфейсе как требующее
  проверки (в отличие от обычного автозаполнения), но подставляется сразу.
- Сбой распознавания (нет Tesseract, битая картинка, нет языкового пакета)
  никогда не должен приводить к ошибке всего запроса — поле просто остаётся
  `null`, как и без этой функции.
- Платформа — Windows; пути через `pathlib.Path`.
- Дизайн: `docs/superpowers/specs/2026-08-10-ocr-image-fallback-design.md`.

---

## Task 1: Установка Tesseract OCR и Python-зависимостей

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Produces: рабочий движок Tesseract OCR с русским языковым пакетом,
  доступный из Python через `pytesseract`; сборка Pillow для открытия картинок.

- [ ] **Step 1: Установить движок Tesseract OCR**

```bash
choco install tesseract -y
```

Ожидается: устанавливается в `C:\Program Files\Tesseract-OCR\`.

- [ ] **Step 2: Проверить, что движок работает**

```bash
"C:\Program Files\Tesseract-OCR\tesseract.exe" --version
```

Ожидается: печатает версию, например `tesseract 5.x.x`.

- [ ] **Step 3: Скачать русский языковой пакет**

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/rus.traineddata" -OutFile "C:\Program Files\Tesseract-OCR\tessdata\rus.traineddata"
```

Ожидается: файл `rus.traineddata` появляется в папке `tessdata`.

- [ ] **Step 4: Добавить Python-зависимости**

`requirements.txt`:
```
Flask>=3.0,<4.0
pytesseract>=0.3,<0.4
Pillow>=10.0,<13.0
```

```bash
pip install -r requirements-dev.txt
```

- [ ] **Step 5: Проверить всё вместе из Python**

```bash
python -c "import pytesseract; print(pytesseract.get_tesseract_version()); print('rus' in pytesseract.get_languages())"
```

Ожидается: печатает номер версии, затем `True`.

Если команда падает с `TesseractNotFoundError` (PATH не обновился после
установки) — выполнить проверку так, указав путь явно, и убедиться что
после этого работает:
```bash
python -c "import pytesseract; pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'; print(pytesseract.get_tesseract_version())"
```
`app/ocr.py` в Task 3 уже учитывает эту ситуацию программно — эта проверка
здесь просто убеждается, что сам движок и языковые данные на месте.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt
git commit -m "chore: add pytesseract and Pillow for OCR fallback extraction"
```

---

## Task 2: `document_reader.py` — извлечение картинок из .docx

**Files:**
- Modify: `tests/helpers.py`
- Modify: `app/document_reader.py`
- Test: `tests/test_document_reader.py`

**Interfaces:**
- Consumes: ничего нового (расширяет существующий `read_docx`).
- Produces:
  - `DocxContent.images: list[bytes]` — новое поле, по умолчанию `[]`
    (`field(default_factory=list)`), так что все существующие места, где
    `DocxContent(paragraphs=..., tables=...)` создаётся без `images`,
    продолжают работать без изменений.
  - `tests/helpers.py`: `build_docx_bytes(doc_xml, extra_files=None)` и
    `make_docx(tmp_path, doc_xml, filename="test.docx", extra_files=None)` —
    оба принимают новый необязательный параметр `extra_files: dict[str, bytes]`
    (путь в архиве → байты), который просто дописывается в zip-архив.

- [ ] **Step 1: Добавить `extra_files` в `tests/helpers.py`**

Изменить `build_docx_bytes` и `make_docx`:

```python
def build_docx_bytes(doc_xml, extra_files=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc_xml)
        for name, data in (extra_files or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def make_docx(tmp_path, doc_xml, filename="test.docx", extra_files=None):
    path = tmp_path / filename
    path.write_bytes(build_docx_bytes(doc_xml, extra_files=extra_files))
    return path
```

- [ ] **Step 2: Написать падающие тесты**

Добавить в `tests/test_document_reader.py`:

```python
def test_read_embedded_image(tmp_path):
    xml = document_xml(paragraphs=["Текст"])
    png_bytes = b"\x89PNG\r\n\x1a\nfake-image-data"
    path = make_docx(tmp_path, xml, extra_files={"word/media/image1.png": png_bytes})
    content = read_docx(path)
    assert content.images == [png_bytes]


def test_read_no_images_is_empty_list(tmp_path):
    xml = document_xml(paragraphs=["Текст"])
    path = make_docx(tmp_path, xml)
    content = read_docx(path)
    assert content.images == []


def test_read_ignores_non_image_media(tmp_path):
    xml = document_xml(paragraphs=["Текст"])
    path = make_docx(
        tmp_path, xml,
        extra_files={"word/media/chart1.emf": b"not-supported-format"},
    )
    content = read_docx(path)
    assert content.images == []
```

(`from tests.helpers import document_xml, make_docx` уже есть в файле — не
менять существующий импорт.)

- [ ] **Step 3: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_document_reader.py -v
```

Ожидается: `AttributeError: 'DocxContent' object has no attribute 'images'`.

- [ ] **Step 4: Реализовать в `app/document_reader.py`**

Изменить импорт:
```python
from dataclasses import dataclass, field
```

Добавить константу рядом с `ALTERNATE_CONTENT`:
```python
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.tif')
```

Изменить `DocxContent`:
```python
@dataclass
class DocxContent:
    paragraphs: list
    tables: list
    images: list = field(default_factory=list)
```

Изменить `read_docx`:
```python
def read_docx(path) -> DocxContent:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            with z.open('word/document.xml') as f:
                tree = ElementTree.parse(f)
            images = [
                z.read(name)
                for name in z.namelist()
                if name.startswith('word/media/') and name.lower().endswith(IMAGE_EXTENSIONS)
            ]
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise DocxReadError(f"Cannot read {path}: {e}") from e

    body = tree.getroot().find(_qn('body'))
    if body is None:
        raise DocxReadError(f"Cannot read {path}: no <w:body> element in word/document.xml")

    paragraphs = []
    tables = []
    _walk(body, paragraphs, tables)

    return DocxContent(paragraphs=paragraphs, tables=tables, images=images)
```

- [ ] **Step 5: Запустить тесты, убедиться что проходят**

```bash
pytest tests/test_document_reader.py -v
```

Ожидается: все тесты `PASSED`, включая уже существовавшие (проверить, что
ничего не сломалось: `test_read_paragraphs`, `test_read_tables` и т.д.).

- [ ] **Step 6: Commit**

```bash
git add app/document_reader.py tests/helpers.py tests/test_document_reader.py
git commit -m "feat: extract embedded raster images from docx"
```

---

## Task 3: `app/ocr.py` — распознавание текста с картинки

**Files:**
- Create: `app/ocr.py`
- Test: `tests/test_ocr.py`

**Interfaces:**
- Consumes: `list[bytes]` — сырые байты картинок (из `DocxContent.images`,
  Task 2).
- Produces:
  - `recognize_text(images: list[bytes]) -> list[str]` — по одной строке
    распознанного текста на каждую картинку (пустая строка, если картинку
    не удалось прочитать или распознать). **Никогда не бросает исключений.**

- [ ] **Step 1: Написать падающие тесты**

`tests/test_ocr.py`:
```python
import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from app import ocr


def _text_image(text):
    img = Image.new("RGB", (700, 150), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=48)
    draw.text((10, 30), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _tesseract_available():
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def test_recognize_text_reads_clear_text():
    if not _tesseract_available():
        pytest.skip("Tesseract OCR не установлен в этой среде")
    result = ocr.recognize_text([_text_image("HELLO 12345")])
    assert len(result) == 1
    assert "12345" in result[0]


def test_recognize_text_ignores_unreadable_image():
    result = ocr.recognize_text([b"not an image at all"])
    assert result == [""]


def test_recognize_text_empty_list():
    assert ocr.recognize_text([]) == []


def test_recognize_text_preserves_order_and_count():
    result = ocr.recognize_text([b"bad-1", b"bad-2", b"bad-3"])
    assert result == ["", "", ""]
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_ocr.py -v
```

Ожидается: `ModuleNotFoundError: No module named 'app.ocr'`.

- [ ] **Step 3: Реализовать `app/ocr.py`**

```python
import io

import pytesseract
from PIL import Image

DEFAULT_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _ocr_image(img):
    try:
        return pytesseract.image_to_string(img, lang="rus")
    except pytesseract.TesseractNotFoundError:
        # PATH may not include Tesseract until the shell/session restarts
        # after installing it; the standard Windows installer always puts
        # it at this location, so retry once by pointing at it directly.
        pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESSERACT_CMD
        return pytesseract.image_to_string(img, lang="rus")


def recognize_text(images: list) -> list:
    """Best-effort OCR over each image's raw bytes.

    Never raises: an image that can't be opened (bad format, corrupt data)
    or a missing/misconfigured Tesseract installation both just contribute
    an empty string for that image, so a caller never needs its own
    try/except around this.
    """
    texts = []
    for data in images:
        try:
            img = Image.open(io.BytesIO(data))
            texts.append(_ocr_image(img))
        except Exception:
            texts.append("")
    return texts
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

```bash
pytest tests/test_ocr.py -v
```

Ожидается: все тесты `PASSED` (если Tesseract установлен из Task 1 —
`test_recognize_text_reads_clear_text` реально распознаёт текст, а не
пропускается).

- [ ] **Step 5: Commit**

```bash
git add app/ocr.py tests/test_ocr.py
git commit -m "feat: add OCR module for recognizing text in embedded images"
```

---

## Task 4: `extractors.py` — уточнение токенов площади + текстовый резервный поиск

**Files:**
- Modify: `app/extractors.py`
- Test: `tests/test_extractors.py`

**Interfaces:**
- Consumes: `parse_number` (уже существует в этом файле).
- Produces:
  - Изменённые `extract_aboveground_area`, `extract_total_area` (те же
    сигнатуры, точнее критерий отбора строки).
  - `_find_area_value(tables, must_contain, must_not_contain=())` —
    существующая функция получает новый необязательный параметр (обратно
    совместимо).
  - Новая `_find_area_value_in_text(lines: list[str], must_contain, must_not_contain=()) -> float | None` —
    аналог `_find_area_value`, но для плоского списка строк вместо таблицы;
    используется в Task 5 из `passport.py`.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_extractors.py`:

```python
def test_extract_aboveground_area_accepts_nazemnaya_variant():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Общая наземная площадь", "м2", "54 116"]]],
    )
    assert extractors.extract_aboveground_area(tz) == 54116.0


def test_extract_total_area_ignores_subarea_rows():
    tz = DocxContent(
        paragraphs=[],
        tables=[[
            ["1", "Общая площадь подземного паркинга", "м2", "13 297"],
            ["2", "Общая наземная площадь", "м2", "54 116"],
            ["3", "Общая площадь", "м2", "67 413"],
        ]],
    )
    assert extractors.extract_total_area(tz) == 67413.0


def test_find_area_value_in_text_same_line():
    lines = ["Общая площадь м2 67 413"]
    value = extractors._find_area_value_in_text(
        lines, ('обща', 'площад'),
        must_not_contain=('подземн', 'надземн', 'наземн'),
    )
    assert value == 67413.0


def test_find_area_value_in_text_next_line():
    lines = ["Площадь подземной части", "м2 13 297"]
    assert extractors._find_area_value_in_text(lines, ('площад', 'подземн')) == 13297.0


def test_find_area_value_in_text_disambiguates_total_from_subareas():
    lines = [
        "Общая площадь подземного паркинга м2 13 297",
        "Общая наземная площадь м2 54 116",
        "Общая площадь м2 67 413",
    ]
    value = extractors._find_area_value_in_text(
        lines, ('обща', 'площад'),
        must_not_contain=('подземн', 'надземн', 'наземн'),
    )
    assert value == 67413.0


def test_find_area_value_in_text_not_found():
    assert extractors._find_area_value_in_text(["Ничего релевантного"], ('обща', 'площад')) is None
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_extractors.py -v
```

Ожидается: `test_extract_aboveground_area_accepts_nazemnaya_variant` и
`test_extract_total_area_ignores_subarea_rows` падают (текущий код находит
не то или ничего); тесты на `_find_area_value_in_text` падают с
`AttributeError: module 'app.extractors' has no attribute '_find_area_value_in_text'`.

- [ ] **Step 3: Реализовать изменения в `app/extractors.py`**

Заменить блок от `def _label_end_index` до `extract_total_area` (включая обе
функции) на:

```python
def _token_matches(token, text):
    if isinstance(token, tuple):
        return any(t in text for t in token)
    return token in text


def _label_matches(label, must_contain, must_not_contain):
    if not all(_token_matches(token, label) for token in must_contain):
        return False
    if any(token in label for token in must_not_contain):
        return False
    return True


def _label_end_index(row, must_contain, must_not_contain=()):
    """Index of the last cell of the label matching ``must_contain``, else None.

    The label has to fit in at most ``MAX_LABEL_CELLS`` adjacent non-numeric
    cells — Word tables sometimes split a caption over two cells, but a label
    is never spread across a whole row. Joining the entire row instead (as the
    previous implementation did) matched rows that merely happen to mention
    the tokens in unrelated columns, e.g. a "количество подземных этажей" row
    that also has a "Площадь застройки" column further right.
    """
    for start in range(len(row)):
        for length in range(1, MAX_LABEL_CELLS + 1):
            window = row[start:start + length]
            if len(window) < length:
                break
            if any(_numeric_cell_value(cell) is not None for cell in window):
                break
            joined = ' '.join(str(cell or '') for cell in window).lower()
            if _label_matches(joined, must_contain, must_not_contain):
                return start + length - 1
    return None


def _find_area_value(tables, must_contain, must_not_contain=()):
    """First number that follows a cell (or cell pair) labelled with the tokens."""
    for table in tables:
        for row in table:
            if not row:
                continue
            end = _label_end_index(row, must_contain, must_not_contain)
            if end is None:
                continue
            for cell in row[end + 1:]:
                value = _numeric_cell_value(cell)
                if value is not None:
                    return value
    return None


LINE_NUMBER_RE = re.compile(r'(?<!\w)[-+]?\d[\d\s]*(?:[.,]\d+)?')


def _last_number_in_line(line):
    matches = LINE_NUMBER_RE.findall(line)
    if not matches:
        return None
    return parse_number(matches[-1])


def _find_area_value_in_text(lines, must_contain, must_not_contain=()):
    """Like ``_find_area_value``, but over flat text lines (e.g. OCR output)
    instead of table rows: a label and its number don't sit in separate grid
    cells, so the number is taken from the rest of the matching line, or —
    if the label fills the whole line — from the line right after it."""
    for i, line in enumerate(lines):
        label = line.lower()
        if not _label_matches(label, must_contain, must_not_contain):
            continue
        value = _last_number_in_line(line)
        if value is not None:
            return value
        if i + 1 < len(lines):
            value = _last_number_in_line(lines[i + 1])
            if value is not None:
                return value
    return None


def extract_underground_area(tz):
    return _find_area_value(tz.tables, ('площад', 'подземн'))


def extract_aboveground_area(tz):
    return _find_area_value(tz.tables, ('площад', ('надземн', 'наземн')))


def extract_total_area(tz):
    return _find_area_value(
        tz.tables, ('обща', 'площад'),
        must_not_contain=('подземн', 'надземн', 'наземн'),
    )
```

`LINE_NUMBER_RE` использует `(?<!\w)` перед числом, чтобы не "прилипать" к
цифре внутри единицы измерения (например, не спутать "2" из "м2" с началом
отдельного числа) — то же самое соображение, что уже решено для
`NUMERIC_CELL_RE` в ячейках таблиц, только для текста строк вместо ячеек.

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

```bash
pytest tests/test_extractors.py -v
```

Ожидается: все тесты `PASSED`, включая уже существовавшие (важно —
`test_extract_underground_area_found`, `test_extract_underground_area_ignores_floor_count_row`,
`test_extract_underground_area_ignores_floor_count_row_with_area_column`,
`test_extract_area_skips_unit_cell_as_value`, `test_extract_building_class_*`
и все `test_real_*` не должны сломаться).

- [ ] **Step 5: Commit**

```bash
git add app/extractors.py tests/test_extractors.py
git commit -m "fix: recognize наземная as aboveground area, disambiguate total from subareas, add text-based area fallback"
```

---

## Task 5: `passport.py` — резервный проход через OCR

**Files:**
- Modify: `app/passport.py`
- Test: `tests/test_passport.py`

**Interfaces:**
- Consumes:
  - `app.ocr.recognize_text(images: list[bytes]) -> list[str]` (Task 3)
  - `app.extractors.extract_general_contractor(dgp)`,
    `extract_signing_year(dgp)`, `extract_building_class(dgp, tz)` — без
    изменений, но теперь также вызываются на "поддельном" `DocxContent`,
    где `paragraphs` — распознанные с картинок строки.
  - `app.extractors._find_area_value_in_text(lines, must_contain, must_not_contain=())` (Task 4)
  - `DocxContent.images` (Task 2)
- Produces: `build_passport(...)` возвращает словарь с новым ключом
  `"ocr_fields": list[str]` — имена полей (из `PASSPORT_FIELDS`, без
  `project_name`), которые удалось заполнить только через OCR-резерв (`[]`,
  если резерв не понадобился или ничего не дал).

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_passport.py` (нужен новый импорт `from app import ocr`
и `from tests.helpers import ...` уже есть — добавить `extra_files` там, где
нужно):

```python
from app import ocr


def test_build_passport_ocr_fallback_fills_area_from_image(tmp_path, monkeypatch):
    # OCR сам по себе не тестируется здесь (см. tests/test_ocr.py и ручную
    # проверку на реальном файле) — только то, что passport.py правильно
    # применяет резерв и помечает поле как заполненное через OCR.
    monkeypatch.setattr(
        ocr, "recognize_text",
        lambda images: ["Общая площадь м2 67 413"] * len(images),
    )
    dgp_xml = document_xml(paragraphs=[
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,"
    ])
    tz_xml = document_xml()
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(
        tmp_path, tz_xml, "tz.docx",
        extra_files={"word/media/image1.png": b"fake-image-bytes"},
    )

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["total_area_sqm"] == 67413.0
    assert result["ocr_fields"] == ["total_area_sqm"]
    # Поля, которых распознанный текст не касается, остаются пустыми:
    assert result["underground_area_sqm"] is None
    assert result["aboveground_area_sqm"] is None


def test_build_passport_skips_ocr_when_nothing_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ocr, "recognize_text",
        lambda images: calls.append(images) or [""] * len(images),
    )
    # Every one of the 6 fields is resolvable from ordinary text/tables, so
    # the OCR fallback's "if not missing: return []" guard should fire
    # before recognize_text is ever called — even though the DGP has an
    # attached image, proving the fallback is lazy, not eager.
    dgp_xml = document_xml(paragraphs=[
        "г. Москва",
        "«04» февраля 2025 г.",
        "Жилой комплекс бизнес-класса.",
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,",
    ])
    tz_xml = document_xml(tables=[[
        ["1", "Площадь подземной части", "м2", "1 000"],
        ["2", "Площадь надземной части", "м2", "2 000"],
        ["3", "Общая площадь", "м2", "3 000"],
    ]])
    dgp_path = make_docx(
        tmp_path, dgp_xml, "dgp.docx",
        extra_files={"word/media/image1.png": b"unused-because-nothing-is-missing"},
    )
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["ocr_fields"] == []
    assert calls == []


def test_build_passport_ocr_failure_leaves_field_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "recognize_text", lambda images: [""] * len(images))
    dgp_xml = document_xml()
    tz_xml = document_xml()
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(
        tmp_path, tz_xml, "tz.docx",
        extra_files={"word/media/image1.png": b"fake-image-bytes"},
    )

    result = passport.build_passport("Тест", dgp_path, tz_path)

    assert result["total_area_sqm"] is None
    assert result["ocr_fields"] == []
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_passport.py -v
```

Ожидается: `KeyError: 'ocr_fields'` (или `assert None == 67413.0`) — резерв
через OCR ещё не реализован.

- [ ] **Step 3: Реализовать в `app/passport.py`**

```python
import json
from pathlib import Path

from . import extractors, ocr
from .document_reader import DocxContent, read_docx

PASSPORT_FIELDS = [
    "project_name", "year_signed", "building_class",
    "general_contractor", "underground_area_sqm",
    "aboveground_area_sqm", "total_area_sqm",
]

FIELD_LABELS = {
    "project_name": "Название проекта",
    "year_signed": "Год подписания договора",
    "building_class": "Класс здания",
    "general_contractor": "Генподрядчик",
    "underground_area_sqm": "Площадь подземной части, м²",
    "aboveground_area_sqm": "Площадь надземной части, м²",
    "total_area_sqm": "Общая площадь комплекса, м²",
}

TEXT_FIELDS = ("year_signed", "building_class", "general_contractor")
AREA_FIELDS = ("underground_area_sqm", "aboveground_area_sqm", "total_area_sqm")

AREA_TOKENS = {
    "underground_area_sqm": (('площад', 'подземн'), ()),
    "aboveground_area_sqm": (('площад', ('надземн', 'наземн')), ()),
    "total_area_sqm": (('обща', 'площад'), ('подземн', 'надземн', 'наземн')),
}


def _ocr_lines(images):
    if not images:
        return []
    lines = []
    for text in ocr.recognize_text(images):
        lines.extend(text.splitlines())
    return lines


def _apply_ocr_fallback(data, dgp, tz):
    missing = [f for f in PASSPORT_FIELDS if f != "project_name" and data[f] is None]
    if not missing:
        return []

    needs_dgp_ocr = any(f in TEXT_FIELDS for f in missing)
    needs_tz_ocr = any(f in TEXT_FIELDS or f in AREA_FIELDS for f in missing)

    dgp_lines = _ocr_lines(dgp.images) if needs_dgp_ocr else []
    tz_lines = _ocr_lines(tz.images) if needs_tz_ocr else []

    ocr_dgp = DocxContent(paragraphs=dgp_lines, tables=[])
    ocr_tz = DocxContent(paragraphs=tz_lines, tables=[])

    filled = []
    if data["general_contractor"] is None:
        value = extractors.extract_general_contractor(ocr_dgp)
        if value is not None:
            data["general_contractor"] = value
            filled.append("general_contractor")
    if data["year_signed"] is None:
        value = extractors.extract_signing_year(ocr_dgp)
        if value is not None:
            data["year_signed"] = value
            filled.append("year_signed")
    if data["building_class"] is None:
        value = extractors.extract_building_class(ocr_dgp, ocr_tz)
        if value is not None:
            data["building_class"] = value
            filled.append("building_class")
    for field in AREA_FIELDS:
        if data[field] is not None:
            continue
        must_contain, must_not_contain = AREA_TOKENS[field]
        value = extractors._find_area_value_in_text(tz_lines, must_contain, must_not_contain)
        if value is not None:
            data[field] = value
            filled.append(field)
    return filled


def build_passport(project_name: str, dgp_path, tz_path) -> dict:
    dgp = read_docx(dgp_path)
    tz = read_docx(tz_path)
    data = {
        "project_name": project_name,
        "year_signed": extractors.extract_signing_year(dgp),
        "building_class": extractors.extract_building_class(dgp, tz),
        "general_contractor": extractors.extract_general_contractor(dgp),
        "underground_area_sqm": extractors.extract_underground_area(tz),
        "aboveground_area_sqm": extractors.extract_aboveground_area(tz),
        "total_area_sqm": extractors.extract_total_area(tz),
    }
    data["ocr_fields"] = _apply_ocr_fallback(data, dgp, tz)
    return data


def save_passport(passport_data: dict, path: Path) -> None:
    path.write_text(
        json.dumps(passport_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_passport(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

```bash
pytest tests/test_passport.py -v
```

Ожидается: все тесты `PASSED`. Также прогнать полный набор, чтобы убедиться,
что ничего не сломалось из-за нового ключа `ocr_fields` в возвращаемом
словаре:

```bash
pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add app/passport.py tests/test_passport.py
git commit -m "feat: fall back to OCR-recognized text when a field isn't found in the document text"
```

---

## Task 6: Интерфейс — отображение и снятие отметки "с картинки"

**Files:**
- Modify: `app/routes.py`
- Modify: `app/templates/project.html`
- Modify: `app/static/style.css`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `passport["ocr_fields"]` (Task 5).
- Produces: `project_page` передаёт в шаблон `ocr_fields`; `update_project`
  снимает поле из `ocr_fields`, если пользователь сохранил для него другое
  значение (оставляет отметку, если значение не менялось).

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_routes.py`:

```python
def test_project_page_flags_ocr_filled_field(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "ОКР проект")
    passport_module.save_passport({
        "project_name": "ОКР проект",
        "year_signed": None,
        "building_class": None,
        "general_contractor": None,
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": 67413.0,
        "ocr_fields": ["total_area_sqm"],
    }, storage.passport_path(tmp_path, slug))

    resp = client.get(f"/projects/{slug}")
    assert resp.status_code == 200
    assert "С картинки".encode("utf-8") in resp.data


def test_update_project_clears_ocr_flag_when_value_changed(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "ОКР правка")
    path = storage.passport_path(tmp_path, slug)
    passport_module.save_passport({
        "project_name": "ОКР правка",
        "year_signed": None,
        "building_class": None,
        "general_contractor": None,
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": 67413.0,
        "ocr_fields": ["total_area_sqm"],
    }, path)

    client.post(f"/projects/{slug}", data={"total_area_sqm": "70000"})

    saved = passport_module.load_passport(path)
    assert saved["total_area_sqm"] == 70000.0
    assert saved["ocr_fields"] == []


def test_update_project_keeps_ocr_flag_when_value_unchanged(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "ОКР без правки")
    path = storage.passport_path(tmp_path, slug)
    passport_module.save_passport({
        "project_name": "ОКР без правки",
        "year_signed": None,
        "building_class": None,
        "general_contractor": None,
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": 67413.0,
        "ocr_fields": ["total_area_sqm"],
    }, path)

    client.post(f"/projects/{slug}", data={"total_area_sqm": "67413"})

    saved = passport_module.load_passport(path)
    assert saved["ocr_fields"] == ["total_area_sqm"]
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_routes.py -v
```

Ожидается: первый тест падает, так как в HTML нет текста "С картинки";
второй и третий — `ocr_fields` в сохранённом JSON не совпадает с ожидаемым
(отметка сейчас никак не обрабатывается).

- [ ] **Step 3: Изменить `app/routes.py`**

В `project_page` добавить передачу `ocr_fields`:

```python
@bp.route("/projects/<slug>", methods=["GET"])
def project_page(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)
    data = passport_module.load_passport(path)
    return render_template(
        "project.html",
        slug=slug,
        passport=data,
        fields=passport_module.PASSPORT_FIELDS,
        field_labels=passport_module.FIELD_LABELS,
        ocr_fields=data.get("ocr_fields", []),
    )
```

Заменить `update_project` целиком:

```python
@bp.route("/projects/<slug>", methods=["POST"])
def update_project(slug):
    root = _projects_root()
    if slug not in storage.list_project_slugs(root):
        abort(404)
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)
    data = passport_module.load_passport(path)
    ocr_fields = list(data.get("ocr_fields", []))
    for field in passport_module.PASSPORT_FIELDS:
        if field == "project_name":
            continue
        old_value = data.get(field)
        raw_value = request.form.get(field, "").strip()
        if not raw_value:
            new_value = None
        elif field in AREA_FIELDS:
            new_value = extractors.parse_number(raw_value)
        else:
            new_value = raw_value
        data[field] = new_value
        if new_value != old_value and field in ocr_fields:
            ocr_fields.remove(field)
    data["ocr_fields"] = ocr_fields
    passport_module.save_passport(data, path)
    return redirect(url_for("main.project_page", slug=slug))
```

- [ ] **Step 4: Изменить `app/templates/project.html`**

Заменить блок цикла по полям:

```html
{% extends "base.html" %}
{% block content %}
<div class="page-head">
  <div>
    <a class="back-link" href="{{ url_for('main.index') }}">&larr; Все проекты</a>
    <h1>{{ passport.project_name }}</h1>
    <p class="page-sub">
      Зелёный значок — заполнено автоматически из текста документа. Синий —
      распознано с картинки, стоит проверить. Жёлтый — заполните вручную.
    </p>
  </div>
</div>

<form method="post" action="{{ url_for('main.update_project', slug=slug) }}">
  <div class="card fields-card">
    {% for field in fields %}
      {% if field != "project_name" %}
      {% set value = passport[field] %}
      {% set is_ocr = field in ocr_fields %}
      <div class="field-row {{ 'is-empty' if value is none else ('is-ocr' if is_ocr else 'is-filled') }}">
        <div class="field-label-col">
          <span class="field-label">{{ field_labels.get(field, field) }}</span>
          {% if value is none %}
            <span class="badge badge-warning">Заполните вручную</span>
          {% elif is_ocr %}
            <span class="badge badge-ocr">С картинки — проверьте</span>
          {% else %}
            <span class="badge badge-success">Заполнено автоматически</span>
          {% endif %}
        </div>
        <input type="text" name="{{ field }}" value="{{ value if value is not none else '' }}" placeholder="Введите значение">
      </div>
      {% endif %}
    {% endfor %}
  </div>
  <div class="form-actions">
    <button type="submit" class="btn btn-primary">Сохранить изменения</button>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 5: Добавить стили в `app/static/style.css`**

В блок `:root { ... }` добавить (после строки `--amber-100: #fff3dc;`):
```css
  --blue-600: #2f5fae;
  --blue-100: #e7edfb;
```

В конец файла (после `.badge-warning { ... }`, перед медиа-запросом)
добавить:
```css
.badge-ocr {
  background: var(--blue-100);
  color: var(--blue-600);
}

.field-row.is-ocr input[type="text"] {
  border-color: #b9c9ef;
  background: var(--blue-100);
}
```

- [ ] **Step 6: Запустить тесты, убедиться что проходят**

```bash
pytest tests/ -v
```

Ожидается: все тесты `PASSED`.

- [ ] **Step 7: Commit**

```bash
git add app/routes.py app/templates/project.html app/static/style.css tests/test_routes.py
git commit -m "feat: show and clear the OCR-filled badge on the project page"
```

---

## Task 7: README и ручная проверка на реальном файле-примере

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: приложение целиком (Tasks 1-6).
- Produces: обновлённая инструкция по установке и ручной проверке.

- [ ] **Step 1: Обновить `README.md`**

Заменить содержимое файла на:

```markdown
# Паспорт объекта — извлечение из Word

## Установка

    pip install -r requirements-dev.txt

Для резервного распознавания полей с картинок дополнительно нужен
Tesseract OCR с русским языковым пакетом:

    choco install tesseract -y
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/rus.traineddata" -OutFile "C:\Program Files\Tesseract-OCR\tessdata\rus.traineddata"

Без этого шага приложение продолжает работать как обычно — резервное
распознавание просто ничего не находит, поля с картинок остаются пустыми.

## Запуск

    python run.py

Откройте http://127.0.0.1:5000 в браузере.

## Тесты

    pytest

Тесты, использующие реальные примеры документов (папка `tests/fixtures/`),
пропускаются, если файлы туда не скопированы. Тест на реальное
распознавание текста (`tests/test_ocr.py`) пропускается, если Tesseract не
установлен. Чтобы прогнать всё:

1. Скопируйте `250204 ДГП_Пр_Мира.docx` → `tests/fixtures/dgp_mira.docx`
2. Скопируйте `Прил. 1. Техническое задание Проспект Мира.docx` →
   `tests/fixtures/tz_mira.docx`
3. Установите Tesseract OCR (см. "Установка")
4. Запустите `pytest -v`

## Ручная сквозная проверка

1. `python run.py`
2. Откройте http://127.0.0.1:5000, нажмите "Создать проект"
3. Введите название "Проспект Мира", загрузите те же 2 файла из шага выше
4. После создания должна открыться страница проекта: Генподрядчик = "ООО «АНТТЕК»"
   заполнен автоматически (зелёный значок)
5. Если Tesseract установлен — три поля площади (подземная/надземная/общая)
   должны заполниться значениями, распознанными с картинки на листе 5 ТЗ
   (67 413 / 13 297 / 54 116 м², порядок полей может отличаться), с синим
   значком "С картинки — проверьте". Если Tesseract не установлен или
   распознавание ошиблось — поля остаются пустыми, это ожидаемо, впишите
   значения вручную.
6. Год подписания и класс здания — пустые, подсвечены жёлтым, доступны для
   ручного ввода
7. Впишите значения в пустые поля, нажмите "Сохранить" — после перезагрузки
   страницы введённые значения должны сохраниться, а с полей, заполненных
   через OCR, значок "проверьте" должен исчезнуть, если вы изменили значение
```

- [ ] **Step 2: Выполнить ручную проверку из обновлённого README**

Пройти шаги 1-7 из раздела "Ручная сквозная проверка", убедиться что
поведение совпадает с описанным. Если распознавание картинки на реальном
файле даёт неточный результат (OCR не идеален) — задокументировать здесь же,
в отчёте о выполнении задачи, фактически увиденные значения, не подгоняя
код под конкретные цифры.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document OCR setup and update manual verification steps"
```
