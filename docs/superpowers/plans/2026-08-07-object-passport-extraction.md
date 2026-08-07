# Извлечение паспорта объекта из Word — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Локальное Flask-приложение, где пользователь создаёт проект, загружает 2 .docx-файла (Договор генподряда — ДГП, Техническое задание — ТЗ), и приложение автоматически извлекает 6 полей "паспорта объекта" в `passport.json`, оставляя ненайденные поля пустыми и редактируемыми вручную.

**Architecture:** Flask-приложение с файловым хранением (без БД): `document_reader.py` разбирает .docx в текст+таблицы через стандартную библиотеку, `extractors.py` содержит 6 функций разбора по правилам (regex/поиск по таблицам), `passport.py` собирает и сохраняет результат как JSON, `storage.py` управляет папками проектов на диске, `routes.py` связывает всё через веб-формы.

**Tech Stack:** Python 3, Flask (единственная runtime-зависимость), pytest (тесты), стандартная библиотека (`zipfile`, `xml.etree.ElementTree`, `re`, `json`, `pathlib`) для разбора .docx — без python-docx/pandoc.

## Global Constraints

- Никаких внешних облачных LLM/API — вся обработка на своей машине.
- Заполнение полей полностью автоматическое, без шага подтверждения; ненайденное поле = `null` в JSON, помечается в интерфейсе как требующее ручного ввода.
- Без базы данных: один проект = одна папка на диске (`storage/projects/<slug>/`) с исходными файлами и `passport.json`.
- Единственная runtime-зависимость — Flask. Чтение .docx — только через `zipfile` + `xml.etree.ElementTree` (нет python-docx/pandoc в среде).
- Платформа — Windows; все пути через `pathlib.Path`.
- Спецификация: `docs/superpowers/specs/2026-08-07-object-passport-extraction-design.md`.

---

## Task 1: Каркас проекта

**Files:**
- Create: `app/__init__.py` (пустой файл-маркер пакета)
- Create: `tests/__init__.py` (пустой файл-маркер пакета)
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.gitignore`

**Interfaces:**
- Produces: пакеты `app` и `tests`, доступные для импорта; `requirements-dev.txt` устанавливает всё нужное для разработки и тестов.

- [ ] **Step 1: Создать структуру папок и пустые файлы-пакеты**

```bash
mkdir app
mkdir tests
mkdir tests/fixtures
type nul > app/__init__.py
type nul > tests/__init__.py
```

- [ ] **Step 2: Написать `requirements.txt`**

```
Flask>=3.0,<4.0
```

- [ ] **Step 3: Написать `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0,<9.0
```

- [ ] **Step 4: Написать `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
storage/
tests/fixtures/*.docx
```

- [ ] **Step 5: Установить зависимости и проверить, что пакеты импортируются**

```bash
pip install -r requirements-dev.txt
python -c "import app; import tests; print('ok')"
```

Ожидается: вывод `ok`, без ошибок импорта.

- [ ] **Step 6: Commit**

```bash
git add app/__init__.py tests/__init__.py requirements.txt requirements-dev.txt .gitignore
git commit -m "chore: scaffold project structure"
```

---

## Task 2: `storage.py` — управление папками проектов

**Files:**
- Create: `app/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces:
  - `slugify(name: str) -> str` — превращает название проекта в безопасное имя папки, бросает `ValueError` если после очистки имя пустое.
  - `unique_slug(root: Path, base_slug: str) -> str` — возвращает `base_slug`, либо `base_slug_2`, `base_slug_3`... если уже занято.
  - `create_project(root: Path, project_name: str) -> str` — создаёт папку проекта (и `raw/` внутри неё), возвращает итоговый slug.
  - `raw_dir(root: Path, slug: str) -> Path`
  - `passport_path(root: Path, slug: str) -> Path`
  - `list_project_slugs(root: Path) -> list[str]`

- [ ] **Step 1: Написать падающие тесты**

`tests/test_storage.py`:
```python
import pytest
from app import storage


def test_slugify_replaces_spaces():
    assert storage.slugify("Проспект Мира") == "Проспект_Мира"


def test_slugify_strips_invalid_chars():
    assert storage.slugify('One:Tower/2*?') == "OneTower2"


def test_slugify_empty_raises():
    with pytest.raises(ValueError):
        storage.slugify("   ")


def test_unique_slug_returns_base_when_free(tmp_path):
    assert storage.unique_slug(tmp_path, "mira") == "mira"


def test_unique_slug_appends_number_when_taken(tmp_path):
    (tmp_path / "mira").mkdir()
    assert storage.unique_slug(tmp_path, "mira") == "mira_2"


def test_create_project_creates_raw_dir(tmp_path):
    slug = storage.create_project(tmp_path, "Проспект Мира")
    assert (tmp_path / slug / "raw").is_dir()


def test_create_project_avoids_collision(tmp_path):
    slug1 = storage.create_project(tmp_path, "Мира")
    slug2 = storage.create_project(tmp_path, "Мира")
    assert slug1 != slug2


def test_list_project_slugs_on_empty_root(tmp_path):
    empty_root = tmp_path / "does_not_exist_yet"
    assert storage.list_project_slugs(empty_root) == []


def test_list_project_slugs_returns_sorted_names(tmp_path):
    storage.create_project(tmp_path, "Bravo")
    storage.create_project(tmp_path, "Alpha")
    assert storage.list_project_slugs(tmp_path) == ["Alpha", "Bravo"]


def test_raw_dir_and_passport_path(tmp_path):
    assert storage.raw_dir(tmp_path, "mira") == tmp_path / "mira" / "raw"
    assert storage.passport_path(tmp_path, "mira") == tmp_path / "mira" / "passport.json"
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
pytest tests/test_storage.py -v
```

Ожидается: `ModuleNotFoundError` или `AttributeError` — в `app/storage.py` пока ничего нет.

- [ ] **Step 3: Реализовать `app/storage.py`**

```python
import re
from pathlib import Path

INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*]')
WHITESPACE_RE = re.compile(r'\s+')


def slugify(name: str) -> str:
    name = name.strip()
    name = INVALID_CHARS_RE.sub('', name)
    name = WHITESPACE_RE.sub('_', name.strip())
    if not name:
        raise ValueError("project name is empty after cleanup")
    return name


def unique_slug(root: Path, base_slug: str) -> str:
    candidate = base_slug
    n = 2
    while (root / candidate).exists():
        candidate = f"{base_slug}_{n}"
        n += 1
    return candidate


def project_dir(root: Path, slug: str) -> Path:
    return root / slug


def raw_dir(root: Path, slug: str) -> Path:
    return project_dir(root, slug) / "raw"


def passport_path(root: Path, slug: str) -> Path:
    return project_dir(root, slug) / "passport.json"


def create_project(root: Path, project_name: str) -> str:
    root.mkdir(parents=True, exist_ok=True)
    slug = unique_slug(root, slugify(project_name))
    raw_dir(root, slug).mkdir(parents=True)
    return slug


def list_project_slugs(root: Path) -> list:
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
```

- [ ] **Step 4: Запустить тесты и убедиться, что они проходят**

```bash
pytest tests/test_storage.py -v
```

Ожидается: все тесты `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add app/storage.py tests/test_storage.py
git commit -m "feat: add project folder storage helpers"
```

---

## Task 3: `document_reader.py` — разбор .docx в текст и таблицы

**Files:**
- Create: `app/document_reader.py`
- Create: `tests/helpers.py` (вспомогательный модуль для тестов — создаёт минимальные .docx "на лету", не является тестовым файлом)
- Test: `tests/test_document_reader.py`

**Interfaces:**
- Produces:
  - `DocxContent` (dataclass): поля `paragraphs: list[str]`, `tables: list[list[list[str]]]` (список таблиц, каждая — список строк, каждая строка — список текстов ячеек).
  - `read_docx(path) -> DocxContent`
  - `DocxReadError(Exception)` — при повреждённом/нечитаемом файле.
  - `tests/helpers.py` предоставляет: `document_xml(paragraphs=(), tables=()) -> str`, `build_docx_bytes(document_xml: str) -> bytes`, `make_docx(tmp_path, document_xml, filename="test.docx") -> Path`.

- [ ] **Step 1: Написать вспомогательный модуль для тестов**

`tests/helpers.py`:
```python
import io
import zipfile

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)

RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '</Relationships>'
)


def _paragraph_xml(text):
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _table_xml(rows):
    trs = ""
    for row in rows:
        tcs = "".join(f"<w:tc>{_paragraph_xml(cell)}</w:tc>" for cell in row)
        trs += f"<w:tr>{tcs}</w:tr>"
    return f"<w:tbl>{trs}</w:tbl>"


def document_xml(paragraphs=(), tables=()):
    body = "".join(_paragraph_xml(p) for p in paragraphs)
    body += "".join(_table_xml(t) for t in tables)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body}</w:body></w:document>'
    )


def build_docx_bytes(doc_xml):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


def make_docx(tmp_path, doc_xml, filename="test.docx"):
    path = tmp_path / filename
    path.write_bytes(build_docx_bytes(doc_xml))
    return path
```

- [ ] **Step 2: Написать падающие тесты**

`tests/test_document_reader.py`:
```python
import pytest
from app.document_reader import read_docx, DocxReadError
from tests.helpers import document_xml, make_docx


def test_read_paragraphs(tmp_path):
    xml = document_xml(paragraphs=["Привет", "Мир"])
    path = make_docx(tmp_path, xml)
    content = read_docx(path)
    assert content.paragraphs == ["Привет", "Мир"]


def test_read_tables(tmp_path):
    xml = document_xml(tables=[[["a", "b"], ["c", "d"]]])
    path = make_docx(tmp_path, xml)
    content = read_docx(path)
    assert content.tables == [[["a", "b"], ["c", "d"]]]


def test_read_paragraphs_and_tables_together(tmp_path):
    xml = document_xml(paragraphs=["Заголовок"], tables=[[["1", "2"]]])
    path = make_docx(tmp_path, xml)
    content = read_docx(path)
    assert content.paragraphs == ["Заголовок"]
    assert content.tables == [[["1", "2"]]]


def test_read_broken_zip_raises(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip file at all")
    with pytest.raises(DocxReadError):
        read_docx(path)
```

- [ ] **Step 3: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_document_reader.py -v
```

Ожидается: `ModuleNotFoundError: No module named 'app.document_reader'`.

- [ ] **Step 4: Реализовать `app/document_reader.py`**

```python
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _qn(tag):
    return W_NS + tag


@dataclass
class DocxContent:
    paragraphs: list
    tables: list


class DocxReadError(Exception):
    pass


def read_docx(path) -> DocxContent:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            with z.open('word/document.xml') as f:
                tree = ElementTree.parse(f)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise DocxReadError(f"Cannot read {path}: {e}") from e

    body = tree.getroot().find(_qn('body'))

    paragraphs = []
    for p in body.iter(_qn('p')):
        text = ''.join(t.text or '' for t in p.iter(_qn('t')))
        paragraphs.append(text)

    tables = []
    for tbl in body.iter(_qn('tbl')):
        rows = []
        for tr in tbl.findall(_qn('tr')):
            cells = []
            for tc in tr.findall(_qn('tc')):
                cell_text = ''.join(t.text or '' for t in tc.iter(_qn('t')))
                cells.append(cell_text)
            rows.append(cells)
        tables.append(rows)

    return DocxContent(paragraphs=paragraphs, tables=tables)
```

- [ ] **Step 5: Запустить тесты, убедиться что проходят**

```bash
pytest tests/test_document_reader.py -v
```

Ожидается: все тесты `PASSED`.

- [ ] **Step 6: Commit**

```bash
git add app/document_reader.py tests/helpers.py tests/test_document_reader.py
git commit -m "feat: add docx paragraph and table reader"
```

---

## Task 4: `extractors.py` — 6 функций извлечения полей

**Files:**
- Create: `app/extractors.py`
- Create: `tests/conftest.py` (fixtures на реальных примерах документов, с пропуском теста если файлов нет)
- Test: `tests/test_extractors.py`

**Interfaces:**
- Consumes: `app.document_reader.DocxContent` (Task 3); `tests/helpers.py: document_xml, make_docx` (Task 3).
- Produces:
  - `parse_number(text: str | None) -> float | None`
  - `extract_general_contractor(dgp: DocxContent) -> str | None`
  - `extract_signing_year(dgp: DocxContent) -> str | None`
  - `extract_building_class(dgp: DocxContent, tz: DocxContent) -> str | None`
  - `extract_underground_area(tz: DocxContent) -> float | None`
  - `extract_aboveground_area(tz: DocxContent) -> float | None`
  - `extract_total_area(tz: DocxContent) -> float | None`

**Перед запуском тестов этого блока:** скопируйте 2 реальных файла-примера в папку `tests/fixtures/` (эта папка не попадает в git — см. `.gitignore` из Task 1):
- `C:\Users\Yerokhov_d\Downloads\250204 ДГП_Пр_Мира.docx` → `tests/fixtures/dgp_mira.docx`
- `C:\Users\Yerokhov_d\Downloads\Прил. 1. Техническое задание Проспект Мира.docx` → `tests/fixtures/tz_mira.docx`

Если файлов нет — тесты, которые их используют, будут пропущены (`SKIPPED`), а не провалены.

- [ ] **Step 1: Написать `tests/conftest.py`**

```python
from pathlib import Path

import pytest

from app.document_reader import read_docx

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DGP_FIXTURE = FIXTURES_DIR / "dgp_mira.docx"
TZ_FIXTURE = FIXTURES_DIR / "tz_mira.docx"


def _require_fixture(path):
    if not path.exists():
        pytest.skip(
            f"Реальный файл-пример не найден: {path}. "
            "Скопируйте его туда перед запуском этого теста (см. план)."
        )


@pytest.fixture(scope="session")
def real_dgp():
    _require_fixture(DGP_FIXTURE)
    return read_docx(DGP_FIXTURE)


@pytest.fixture(scope="session")
def real_tz():
    _require_fixture(TZ_FIXTURE)
    return read_docx(TZ_FIXTURE)
```

- [ ] **Step 2: Написать падающие тесты**

`tests/test_extractors.py`:
```python
from app import extractors
from app.document_reader import DocxContent


# --- parse_number ---

def test_parse_number_thousands_separator():
    assert extractors.parse_number("9 489") == 9489.0


def test_parse_number_decimal_comma():
    assert extractors.parse_number("12 400,5") == 12400.5


def test_parse_number_dash_is_none():
    assert extractors.parse_number("-") is None


def test_parse_number_empty_is_none():
    assert extractors.parse_number("") is None
    assert extractors.parse_number(None) is None


# --- extract_general_contractor (synthetic) ---

def test_extract_general_contractor_synthetic():
    dgp = DocxContent(
        paragraphs=[
            "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
            "именуемое в дальнейшем «Генподрядчик», с третьей стороны,"
        ],
        tables=[],
    )
    assert extractors.extract_general_contractor(dgp) == "ООО «Ромашка»"


def test_extract_general_contractor_not_found():
    dgp = DocxContent(paragraphs=["Ничего релевантного здесь нет."], tables=[])
    assert extractors.extract_general_contractor(dgp) is None


# --- extract_signing_year (synthetic) ---

def test_extract_signing_year_found():
    dgp = DocxContent(
        paragraphs=["г. Москва", "«04» февраля 2025 г."],
        tables=[],
    )
    assert extractors.extract_signing_year(dgp) == "2025"


def test_extract_signing_year_not_found():
    dgp = DocxContent(paragraphs=["г. Москва", ""], tables=[])
    assert extractors.extract_signing_year(dgp) is None


# --- extract_building_class (synthetic) ---

def test_extract_building_class_found():
    dgp = DocxContent(paragraphs=["Жилой комплекс бизнес-класса."], tables=[])
    tz = DocxContent(paragraphs=[], tables=[])
    assert extractors.extract_building_class(dgp, tz) == "Бизнес"


def test_extract_building_class_not_found():
    dgp = DocxContent(paragraphs=["Класс энергоэффективности лифта не ниже B."], tables=[])
    tz = DocxContent(paragraphs=[], tables=[])
    assert extractors.extract_building_class(dgp, tz) is None


# --- area extractors (synthetic) ---

def test_extract_underground_area_found():
    tz = DocxContent(
        paragraphs=[],
        tables=[[
            ["№", "Наименование", "Ед.изм", "Итого"],
            ["1", "Площадь подземной части", "м2", "1 000"],
        ]],
    )
    assert extractors.extract_underground_area(tz) == 1000.0


def test_extract_aboveground_area_found():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Площадь надземной части", "м2", "2 000"]]],
    )
    assert extractors.extract_aboveground_area(tz) == 2000.0


def test_extract_total_area_found():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Общая площадь комплекса", "м2", "3 000"]]],
    )
    assert extractors.extract_total_area(tz) == 3000.0


def test_extract_underground_area_ignores_floor_count_row():
    tz = DocxContent(
        paragraphs=[],
        tables=[[["1", "Количество подземных этажей", "этаж", "2"]]],
    )
    assert extractors.extract_underground_area(tz) is None


# --- real fixtures: documented expectations from the design spec ---

def test_real_general_contractor(real_dgp):
    assert extractors.extract_general_contractor(real_dgp) == "ООО «АНТТЕК»"


def test_real_signing_year_not_present(real_dgp):
    assert extractors.extract_signing_year(real_dgp) is None


def test_real_building_class_not_present(real_dgp, real_tz):
    assert extractors.extract_building_class(real_dgp, real_tz) is None


def test_real_underground_area_not_present(real_tz):
    assert extractors.extract_underground_area(real_tz) is None


def test_real_aboveground_area_not_present(real_tz):
    assert extractors.extract_aboveground_area(real_tz) is None


def test_real_total_area_not_present(real_tz):
    assert extractors.extract_total_area(real_tz) is None
```

- [ ] **Step 3: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_extractors.py -v
```

Ожидается: `ModuleNotFoundError: No module named 'app.extractors'`.

- [ ] **Step 4: Реализовать `app/extractors.py`**

```python
import re

GENERAL_CONTRACTOR_ORG_RE = re.compile(r'\b(?:ООО|АО|ЗАО|ПАО|ОАО)\s*«[^»]+»')
PREAMBLE_CITY_RE = re.compile(r'^г\.?\s*Москва\s*$')
FULL_DATE_RE = re.compile(r'\b\d{2}\.\d{2}\.(20\d{2})\b')
QUOTED_DATE_RE = re.compile(r'«\s*\d{1,2}\s*»\s*[а-яё]+\s+(20\d{2})\s*г', re.IGNORECASE)
BUILDING_CLASS_RE = re.compile(
    r'класс[а-яё\s-]{0,20}(бизнес|премиум|комфорт|эконом|элит)', re.IGNORECASE
)
BUILDING_CLASS_REVERSED_RE = re.compile(
    r'(бизнес|премиум|комфорт|эконом|элит)[а-яё\s-]{0,10}класс', re.IGNORECASE
)
WHITESPACE_RE = re.compile(r'\s+')


def parse_number(text):
    if text is None:
        return None
    t = text.strip()
    if t in ('', '-', '—', '–'):
        return None
    t = WHITESPACE_RE.sub('', t)
    t = t.replace(',', '.')
    t = re.sub(r'[^0-9.\-]', '', t)
    if t in ('', '-', '.', '-.'):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def extract_general_contractor(dgp):
    for para in dgp.paragraphs:
        if 'именуемое в дальнейшем' in para and 'Генподрядчик' in para:
            match = GENERAL_CONTRACTOR_ORG_RE.search(para)
            if match:
                return match.group(0)
    return None


def extract_signing_year(dgp):
    for i, para in enumerate(dgp.paragraphs):
        if PREAMBLE_CITY_RE.match(para.strip()):
            for w in dgp.paragraphs[i:i + 2]:
                m = FULL_DATE_RE.search(w) or QUOTED_DATE_RE.search(w)
                if m:
                    return m.group(1)
            break
    return None


def extract_building_class(dgp, tz):
    for doc in (dgp, tz):
        for para in doc.paragraphs:
            m = BUILDING_CLASS_RE.search(para) or BUILDING_CLASS_REVERSED_RE.search(para)
            if m:
                return m.group(1).capitalize()
    return None


def _find_area_value(tables, must_contain):
    for table in tables:
        for row in table:
            if not row:
                continue
            label = (row[0] or '').lower()
            if all(token in label for token in must_contain):
                for cell in reversed(row[1:]):
                    value = parse_number(cell)
                    if value is not None:
                        return value
    return None


def extract_underground_area(tz):
    return _find_area_value(tz.tables, ('площад', 'подземн'))


def extract_aboveground_area(tz):
    return _find_area_value(tz.tables, ('площад', 'надземн'))


def extract_total_area(tz):
    return _find_area_value(tz.tables, ('обща', 'площад'))
```

- [ ] **Step 5: Запустить тесты, убедиться что проходят**

```bash
pytest tests/test_extractors.py -v
```

Ожидается: все тесты `PASSED` (или `SKIPPED` для тестов с `real_dgp`/`real_tz`, если файлы-примеры не скопированы).

- [ ] **Step 6: Commit**

```bash
git add app/extractors.py tests/conftest.py tests/test_extractors.py
git commit -m "feat: add rule-based field extractors"
```

---

## Task 5: `passport.py` — сборка и сохранение паспорта

**Files:**
- Create: `app/passport.py`
- Test: `tests/test_passport.py`

**Interfaces:**
- Consumes: `app.document_reader.read_docx` (Task 3), `app.extractors.extract_*` (Task 4), `tests/helpers.py: document_xml, make_docx` (Task 3).
- Produces:
  - `PASSPORT_FIELDS: list[str]` — `["project_name", "year_signed", "building_class", "general_contractor", "underground_area_sqm", "aboveground_area_sqm", "total_area_sqm"]`
  - `build_passport(project_name: str, dgp_path, tz_path) -> dict`
  - `save_passport(passport: dict, path: Path) -> None`
  - `load_passport(path: Path) -> dict`

- [ ] **Step 1: Написать падающие тесты**

`tests/test_passport.py`:
```python
from app import passport
from tests.helpers import document_xml, make_docx


def test_passport_fields_order():
    assert passport.PASSPORT_FIELDS == [
        "project_name", "year_signed", "building_class",
        "general_contractor", "underground_area_sqm",
        "aboveground_area_sqm", "total_area_sqm",
    ]


def test_build_passport_fills_found_fields_and_nulls_missing(tmp_path):
    dgp_xml = document_xml(paragraphs=[
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,"
    ])
    tz_xml = document_xml(tables=[[["1", "Площадь подземной части", "м2", "1 000"]]])
    dgp_path = make_docx(tmp_path, dgp_xml, "dgp.docx")
    tz_path = make_docx(tmp_path, tz_xml, "tz.docx")

    result = passport.build_passport("Тестовый проект", dgp_path, tz_path)

    assert result["project_name"] == "Тестовый проект"
    assert result["general_contractor"] == "ООО «Ромашка»"
    assert result["underground_area_sqm"] == 1000.0
    assert result["building_class"] is None
    assert result["year_signed"] is None
    assert result["aboveground_area_sqm"] is None
    assert result["total_area_sqm"] is None


def test_save_and_load_passport_roundtrip(tmp_path):
    data = {
        "project_name": "Проспект Мира",
        "year_signed": None,
        "building_class": None,
        "general_contractor": "ООО «АНТТЕК»",
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": None,
    }
    path = tmp_path / "passport.json"
    passport.save_passport(data, path)
    loaded = passport.load_passport(path)
    assert loaded == data


def test_save_passport_writes_readable_utf8(tmp_path):
    data = {"project_name": "Проспект Мира"}
    path = tmp_path / "passport.json"
    passport.save_passport(data, path)
    text = path.read_text(encoding="utf-8")
    assert "Проспект Мира" in text
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_passport.py -v
```

Ожидается: `ModuleNotFoundError: No module named 'app.passport'`.

- [ ] **Step 3: Реализовать `app/passport.py`**

```python
import json
from pathlib import Path

from . import extractors
from .document_reader import read_docx

PASSPORT_FIELDS = [
    "project_name", "year_signed", "building_class",
    "general_contractor", "underground_area_sqm",
    "aboveground_area_sqm", "total_area_sqm",
]


def build_passport(project_name: str, dgp_path, tz_path) -> dict:
    dgp = read_docx(dgp_path)
    tz = read_docx(tz_path)
    return {
        "project_name": project_name,
        "year_signed": extractors.extract_signing_year(dgp),
        "building_class": extractors.extract_building_class(dgp, tz),
        "general_contractor": extractors.extract_general_contractor(dgp),
        "underground_area_sqm": extractors.extract_underground_area(tz),
        "aboveground_area_sqm": extractors.extract_aboveground_area(tz),
        "total_area_sqm": extractors.extract_total_area(tz),
    }


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

Ожидается: все тесты `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add app/passport.py tests/test_passport.py
git commit -m "feat: assemble and persist passport.json"
```

---

## Task 6: Flask-приложение — маршруты и шаблоны

**Files:**
- Modify: `app/__init__.py` — добавить `create_app`
- Create: `app/routes.py`
- Create: `app/templates/base.html`
- Create: `app/templates/index.html`
- Create: `app/templates/new_project.html`
- Create: `app/templates/project.html`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `app.storage.*` (Task 2), `app.passport.*` (Task 5), `tests/helpers.py: document_xml, build_docx_bytes` (Task 3).
- Produces:
  - `create_app(projects_root: Path | None = None) -> flask.Flask`
  - Маршруты: `GET /`, `GET /projects/new`, `POST /projects`, `GET /projects/<slug>`, `POST /projects/<slug>`.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_routes.py`:
```python
import io

from app import create_app
from tests.helpers import build_docx_bytes, document_xml


def _dgp_bytes():
    return build_docx_bytes(document_xml(paragraphs=[
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,"
    ]))


def _tz_bytes():
    return build_docx_bytes(document_xml(tables=[[["1", "Площадь подземной части", "м2", "1 000"]]]))


def test_index_page_loads_when_empty(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200


def test_new_project_form_loads(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.get("/projects/new")
    assert resp.status_code == 200


def test_create_project_rejects_missing_name(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_create_project_rejects_non_docx(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Тест",
        "dgp_file": (io.BytesIO(b"not docx"), "dgp.txt"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_create_project_rejects_corrupted_docx(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Тест",
        "dgp_file": (io.BytesIO(b"this has a .docx name but is not a real zip"), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_create_project_then_view_passport(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Тестовый проект",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 302

    page = client.get(resp.headers["Location"])
    assert page.status_code == 200
    assert "ООО «Ромашка»".encode("utf-8") in page.data


def test_index_lists_created_project(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    client.post("/projects", data={
        "project_name": "Видимый проект",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    resp = client.get("/")
    assert "Видимый_проект".encode("utf-8") in resp.data


def test_update_project_saves_manual_field(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    create_resp = client.post("/projects", data={
        "project_name": "Правка",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    project_url = create_resp.headers["Location"]
    slug = project_url.rstrip("/").rsplit("/", 1)[-1]

    update_resp = client.post(project_url, data={
        "year_signed": "2025",
        "building_class": "Бизнес",
        "general_contractor": "ООО «Ромашка»",
        "underground_area_sqm": "1000",
        "aboveground_area_sqm": "2000",
        "total_area_sqm": "3000",
    })
    assert update_resp.status_code == 302

    from app import passport, storage
    saved = passport.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["building_class"] == "Бизнес"
    assert saved["aboveground_area_sqm"] == 2000.0
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

```bash
pytest tests/test_routes.py -v
```

Ожидается: `ImportError: cannot import name 'create_app' from 'app'`.

- [ ] **Step 3: Написать шаблоны**

`app/templates/base.html`:
```html
<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><title>Паспорта объектов</title></head>
<body>
<h1><a href="{{ url_for('main.index') }}">Паспорта объектов</a></h1>
{% block content %}{% endblock %}
</body>
</html>
```

`app/templates/index.html`:
```html
{% extends "base.html" %}
{% block content %}
<p><a href="{{ url_for('main.new_project_form') }}">Создать проект</a></p>
<ul>
{% for slug in slugs %}
  <li><a href="{{ url_for('main.project_page', slug=slug) }}">{{ slug }}</a></li>
{% endfor %}
</ul>
{% endblock %}
```

`app/templates/new_project.html`:
```html
{% extends "base.html" %}
{% block content %}
{% if error %}<p style="color:red">{{ error }}</p>{% endif %}
<form method="post" action="{{ url_for('main.create_project') }}" enctype="multipart/form-data">
  <p><label>Название проекта: <input type="text" name="project_name"></label></p>
  <p><label>Договор (ДГП), .docx: <input type="file" name="dgp_file"></label></p>
  <p><label>Техническое задание (ТЗ), .docx: <input type="file" name="tz_file"></label></p>
  <button type="submit">Создать</button>
</form>
{% endblock %}
```

`app/templates/project.html`:
```html
{% extends "base.html" %}
{% block content %}
<h2>{{ passport.project_name }}</h2>
<form method="post" action="{{ url_for('main.update_project', slug=slug) }}">
{% for field in fields %}
  {% if field != "project_name" %}
  <p>
    <label>{{ field }}:
      <input type="text" name="{{ field }}"
             value="{{ passport[field] if passport[field] is not none else '' }}"
             {% if passport[field] is none %}style="background:#fff3cd"{% endif %}>
    </label>
  </p>
  {% endif %}
{% endfor %}
<button type="submit">Сохранить</button>
</form>
{% endblock %}
```

- [ ] **Step 4: Реализовать `app/routes.py`**

```python
from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

from . import extractors, passport as passport_module, storage
from .document_reader import DocxReadError

bp = Blueprint("main", __name__)

ALLOWED_EXTENSION = ".docx"
AREA_FIELDS = {"underground_area_sqm", "aboveground_area_sqm", "total_area_sqm"}


def _projects_root():
    return current_app.config["PROJECTS_ROOT"]


@bp.route("/")
def index():
    slugs = storage.list_project_slugs(_projects_root())
    return render_template("index.html", slugs=slugs)


@bp.route("/projects/new", methods=["GET"])
def new_project_form():
    return render_template("new_project.html", error=None)


@bp.route("/projects", methods=["POST"])
def create_project():
    root = _projects_root()
    project_name = request.form.get("project_name", "").strip()
    dgp_file = request.files.get("dgp_file")
    tz_file = request.files.get("tz_file")

    if not project_name:
        return render_template("new_project.html", error="Введите название проекта"), 400
    if not dgp_file or not dgp_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл Договора в формате .docx"), 400
    if not tz_file or not tz_file.filename.lower().endswith(ALLOWED_EXTENSION):
        return render_template("new_project.html", error="Загрузите файл ТЗ в формате .docx"), 400

    slug = storage.create_project(root, project_name)
    raw = storage.raw_dir(root, slug)
    dgp_path = raw / "dgp.docx"
    tz_path = raw / "tz.docx"
    dgp_file.save(dgp_path)
    tz_file.save(tz_path)

    try:
        data = passport_module.build_passport(project_name, dgp_path, tz_path)
    except DocxReadError as e:
        return render_template("new_project.html", error=f"Не удалось прочитать файл: {e}"), 400

    passport_module.save_passport(data, storage.passport_path(root, slug))
    return redirect(url_for("main.project_page", slug=slug))


@bp.route("/projects/<slug>", methods=["GET"])
def project_page(slug):
    root = _projects_root()
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)
    data = passport_module.load_passport(path)
    return render_template(
        "project.html", slug=slug, passport=data, fields=passport_module.PASSPORT_FIELDS
    )


@bp.route("/projects/<slug>", methods=["POST"])
def update_project(slug):
    root = _projects_root()
    path = storage.passport_path(root, slug)
    if not path.exists():
        abort(404)
    data = passport_module.load_passport(path)
    for field in passport_module.PASSPORT_FIELDS:
        if field == "project_name":
            continue
        raw_value = request.form.get(field, "").strip()
        if not raw_value:
            data[field] = None
        elif field in AREA_FIELDS:
            data[field] = extractors.parse_number(raw_value)
        else:
            data[field] = raw_value
    passport_module.save_passport(data, path)
    return redirect(url_for("main.project_page", slug=slug))
```

- [ ] **Step 5: Реализовать `create_app` в `app/__init__.py`**

```python
from pathlib import Path

from flask import Flask


def create_app(projects_root=None):
    app = Flask(__name__)
    app.config["PROJECTS_ROOT"] = Path(
        projects_root or Path(__file__).resolve().parent.parent / "storage" / "projects"
    )

    from . import routes
    app.register_blueprint(routes.bp)

    return app
```

- [ ] **Step 6: Запустить тесты, убедиться что проходят**

```bash
pytest tests/test_routes.py -v
```

Ожидается: все тесты `PASSED`.

- [ ] **Step 7: Commit**

```bash
git add app/__init__.py app/routes.py app/templates tests/test_routes.py
git commit -m "feat: add Flask routes and templates for project passport"
```

---

## Task 7: Точка входа и финальная проверка вручную

**Files:**
- Create: `run.py`
- Create: `README.md`

**Interfaces:**
- Consumes: `app.create_app` (Task 6).
- Produces: `run.py` — точка запуска (`python run.py`).

- [ ] **Step 1: Написать `run.py`**

```python
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
```

- [ ] **Step 2: Написать `README.md`**

```markdown
# Паспорт объекта — извлечение из Word

## Установка

    pip install -r requirements-dev.txt

## Запуск

    python run.py

Откройте http://127.0.0.1:5000 в браузере.

## Тесты

    pytest

Тесты, использующие реальные примеры документов (папка `tests/fixtures/`),
пропускаются, если файлы туда не скопированы. Чтобы прогнать их:

1. Скопируйте `250204 ДГП_Пр_Мира.docx` → `tests/fixtures/dgp_mira.docx`
2. Скопируйте `Прил. 1. Техническое задание Проспект Мира.docx` →
   `tests/fixtures/tz_mira.docx`
3. Запустите `pytest -v`

## Ручная сквозная проверка

1. `python run.py`
2. Откройте http://127.0.0.1:5000, нажмите "Создать проект"
3. Введите название "Проспект Мира", загрузите те же 2 файла из шага выше
4. После создания должна открыться страница проекта: Генподрядчик = "ООО «АНТТЕК»"
   заполнен автоматически; год подписания, класс здания и все 3 площади — пустые,
   подсвечены жёлтым, доступны для ручного ввода
5. Впишите значения в пустые поля, нажмите "Сохранить" — после перезагрузки
   страницы введённые значения должны сохраниться
```

- [ ] **Step 3: Запустить полный набор тестов**

```bash
pytest -v
```

Ожидается: все тесты `PASSED` (тесты на реальных файлах — `PASSED`, если фикстуры скопированы, иначе `SKIPPED`).

- [ ] **Step 4: Выполнить ручную проверку из README**

Пройти шаги 1-5 из раздела "Ручная сквозная проверка" в `README.md`, убедиться что поведение совпадает с описанным.

- [ ] **Step 5: Commit**

```bash
git add run.py README.md
git commit -m "chore: add entry point and README with usage instructions"
```
