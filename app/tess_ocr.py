"""OCR through Tesseract, run as a separate program.

The same contract as ``win_ocr``: ``recognize_page_words`` takes one page as
PNG bytes and returns positioned ``ocr_lines.Word`` objects, already put
through ``ocr_lines.normalize_words`` — so column splitting, the anchors in
``contract_extractors`` and everything after them work on its output
unchanged. Nothing here raises: a missing program, a missing language, a
timeout and an unreadable image all just mean no words.

Where the program and its models are:

- on Windows, the portable build in ``tess_min`` at the project root
  (``tess_min/tesseract.exe``, models in ``tess_min/tessdata``);
- elsewhere — the Docker image — the system ``tesseract`` from apt, with its
  own models;
- either can be overridden: ``KEYPARAMS_TESSERACT_CMD`` for the program,
  ``KEYPARAMS_TESSDATA_DIR`` for the models. The models are always handed
  over as ``--tessdata-dir``, never through ``TESSDATA_PREFIX``, so a stray
  variable on the machine can't quietly swap them.

A page goes through: grey, binarised (and, if switched on, straightened and
stripped of table lines); its orientation found by Tesseract's own OSD, or — when OSD
models are missing or unsure — by trying it every way round as ``win_ocr``
does; then recognised as words with positions.
"""

import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from . import ocr_lines
from .ocr_lines import Word

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTABLE_DIR = PROJECT_ROOT / "tess_min"

CMD_ENV = "KEYPARAMS_TESSERACT_CMD"
TESSDATA_ENV = "KEYPARAMS_TESSDATA_DIR"
PSM_ENV = "KEYPARAMS_TESSERACT_PSM"
TIMEOUT_ENV = "KEYPARAMS_TESSERACT_TIMEOUT"
DESKEW_ENV = "KEYPARAMS_TESSERACT_DESKEW"
BINARIZE_ENV = "KEYPARAMS_TESSERACT_BINARIZE"
REMOVE_LINES_ENV = "KEYPARAMS_TESSERACT_REMOVE_LINES"

# Page preparation, as measured on the five real protocols (stage-1 report):
# binarising gained a field; straightening and removing the table grid each
# lost some — the scans are straight enough, and the grid is what keeps a
# value apart from its label. Both stay available for a crooked batch.
DEFAULT_DESKEW = False
DEFAULT_BINARIZE = True
DEFAULT_REMOVE_LINES = False

LANGUAGES = "rus+eng"
REQUIRED_LANGUAGE = "rus"
OSD_LANGUAGE = "osd"

# Page segmentation: 11 — sparse text, every word found wherever it sits. On
# the five real protocols it read 21 of 24 fields against 7–9 for 6 (one
# uniform block, which runs neighbouring table rows together) and 19 for 4
# and 3. Changeable without touching the code: KEYPARAMS_TESSERACT_PSM.
DEFAULT_PSM = 11

# Seconds one call to the program may take — recognising an A3 page at 300 dpi
# takes a few. Past this the page counts as not read.
DEFAULT_TIMEOUT = 60.0

# The resolution pages are rendered at for this engine, told to the program
# too: PNG bytes on stdin carry no resolution of their own.
RENDER_DPI = 300

# Below this OSD confidence its answer is not trusted and the page is tried
# every way round instead. Upright text of a protocol scores 2.7–3; a page of
# stamps and signatures scores well under 1.
OSD_MIN_CONFIDENCE = 1.5

# The ways a page can be turned, upright first, and enough recognised text to
# call it read — the same rule ``win_ocr`` follows.
ROTATIONS = (0, 90, 180, 270)
READS_PROPERLY = 200

# How far either way straightening looks for the level, and in what steps.
# A scan fed crooked into the scanner is off by a degree or two; much more is
# not a crooked scan but a page on its side, which orientation handles.
MAX_DESKEW_DEGREES = 4.0
DESKEW_STEP = 0.2

# The models the recognition was measured with: tessdata_fast, the same
# files Debian's tesseract-ocr-rus/-eng/-osd packages install (checked
# byte for byte). A different file still works — but its results are no
# longer the ones the golden protocols were checked against, so it's
# logged.
MODEL_SHA256 = {
    "rus.traineddata": "e16e5e036cce1d9ec2b00063cf8b54472625b9e14d893a169e2b0dedeb4df225",
    "eng.traineddata": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "osd.traineddata": "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff",
}

_availability = None


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def tesseract_cmd():
    configured = os.environ.get(CMD_ENV)
    if configured:
        return configured
    if sys.platform == "win32":
        return str(PORTABLE_DIR / "tesseract.exe")
    return "tesseract"


def tessdata_dir():
    """The models' folder, or None to let the program use its own (the
    system install on Linux)."""
    configured = os.environ.get(TESSDATA_ENV)
    if configured:
        return configured
    if sys.platform == "win32":
        return str(PORTABLE_DIR / "tessdata")
    return None


def page_segmentation_mode():
    try:
        return int(os.environ.get(PSM_ENV, DEFAULT_PSM))
    except ValueError:
        return DEFAULT_PSM


def timeout_seconds():
    try:
        return float(os.environ.get(TIMEOUT_ENV, DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def _base_args():
    args = [tesseract_cmd()]
    return args


def _tessdata_args():
    folder = tessdata_dir()
    return ["--tessdata-dir", folder] if folder else []


def _run(args, data=None):
    """Run the program with ``args`` (a list — no shell), ``data`` on stdin.

    Returns stdout decoded as UTF-8. Raises ``subprocess.TimeoutExpired`` past
    the timeout and ``OSError``/``CalledProcessError`` when it can't run.
    """
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        args, input=data, capture_output=True, timeout=timeout_seconds(), check=False, **kwargs,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, args, output=result.stdout, stderr=result.stderr,
        )
    return result.stdout.decode("utf-8", errors="replace")


def _languages():
    """``(folder, languages)`` — where the program takes its models from, as
    it reports it itself, and which ones are there."""
    out = _run(_base_args() + _tessdata_args() + ["--list-langs"])
    lines = out.splitlines()
    # The first line is 'List of available languages in "<folder>" (3):'.
    match = re.search(r'"(.+?)"', lines[0]) if lines else None
    folder = match.group(1) if match else None
    return folder, {line.strip() for line in lines[1:] if line.strip()}


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_models(folder):
    """Names of the models in ``folder`` that differ from ``MODEL_SHA256`` —
    each also warned about in the log. A missing file is not this check's
    business (``availability`` reports a missing Russian model itself)."""
    if not folder:
        return []
    differing = []
    for name, expected in MODEL_SHA256.items():
        path = Path(folder) / name
        if not path.is_file():
            continue
        actual = _sha256(path)
        if actual != expected:
            differing.append(name)
            logger.warning(
                "Tesseract: модель %s отличается от эталонной (SHA-256 %s, ожидалась %s) — "
                "результаты распознавания могут разойтись с проверенными",
                path, actual, expected,
            )
    return differing


def availability():
    """``(available, reason)`` — checked once, on first use.

    ``reason`` is None when available; otherwise it says, in Russian, what is
    missing, for the log and for the page.
    """
    global _availability
    if _availability is not None:
        return _availability
    cmd = tesseract_cmd()
    if not (Path(cmd).is_file() or shutil.which(cmd)):
        _availability = (False, f"не найдена программа Tesseract ({cmd})")
    else:
        try:
            folder, languages = _languages()
        except (OSError, subprocess.SubprocessError) as e:
            _availability = (False, f"Tesseract не запускается: {e}")
        else:
            if REQUIRED_LANGUAGE not in languages:
                _availability = (False, "у Tesseract нет русской модели (rus.traineddata)")
            else:
                _availability = (True, None)
                check_models(folder)
                if OSD_LANGUAGE not in languages:
                    logger.info("Tesseract: нет osd.traineddata — ориентация страницы перебором")
    if _availability[1]:
        logger.warning("Tesseract недоступен: %s", _availability[1])
    return _availability


def available() -> bool:
    return availability()[0]


def reset_availability():
    """Forget the cached check — for tests and for a changed configuration."""
    global _availability
    _availability = None


# --- подготовка страницы ---


def _to_array(image):
    import numpy as np
    return np.array(image.convert("L"))


def skew_angle(gray, span=MAX_DESKEW_DEGREES, step=DESKEW_STEP):
    """The angle, in degrees, that turns the page's lines of text level —
    what ``cv2.getRotationMatrix2D`` takes; 0.0 when it is level already.

    Found by trying small turns of a shrunk copy and keeping the one whose
    rows of ink are sharpest: level lines of text pile their ink into a few
    rows with white gaps between them, a tilted page smears it across all of
    them. Signatures, stamps and a table's frame barely move that score,
    which is what threw off the first attempt — a box around all the ink.
    """
    import cv2
    import numpy as np

    small = cv2.resize(gray, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    _, ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    height, width = ink.shape
    best_angle, best_score = 0.0, -1.0
    steps = int(round(span / step))
    for i in range(-steps, steps + 1):
        angle = i * step
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
        turned = cv2.warpAffine(ink, matrix, (width, height), flags=cv2.INTER_NEAREST, borderValue=0)
        score = float(np.var(turned.sum(axis=1).astype(np.float64)))
        if score > best_score:
            best_angle, best_score = angle, score
    return best_angle


def _deskew(gray):
    """The page turned straight, if it was scanned a little crooked."""
    import cv2

    angle = skew_angle(gray)
    if abs(angle) < DESKEW_STEP / 2:
        return gray
    height, width = gray.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (width, height), flags=cv2.INTER_CUBIC, borderValue=255,
    )


def _remove_table_lines(binary):
    """Long horizontal and vertical strokes — the table grid — painted white,
    so that a cell's border can't be read as "1" or "|" beside its value."""
    import cv2

    inverted = cv2.bitwise_not(binary)
    height, width = binary.shape
    horizontal = cv2.morphologyEx(
        inverted, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(width // 40, 10), 1)),
    )
    vertical = cv2.morphologyEx(
        inverted, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(height // 40, 10))),
    )
    lines = cv2.bitwise_or(horizontal, vertical)
    return cv2.bitwise_not(cv2.bitwise_and(inverted, cv2.bitwise_not(lines)))


def preprocess(image, deskew=None, binarize=None, remove_lines=None):
    """The page as Tesseract gets it: grey; straightened, binarised and
    stripped of table lines as configured. A PIL image.

    Each step is switchable (``KEYPARAMS_TESSERACT_DESKEW``, ``..._BINARIZE``,
    ``..._REMOVE_LINES``) because on the real protocols they don't all help:
    straightening and line removal cost fields, binarisation gained one.
    """
    import cv2

    if deskew is None:
        deskew = _env_flag(DESKEW_ENV, DEFAULT_DESKEW)
    if binarize is None:
        binarize = _env_flag(BINARIZE_ENV, DEFAULT_BINARIZE)
    if remove_lines is None:
        remove_lines = _env_flag(REMOVE_LINES_ENV, DEFAULT_REMOVE_LINES)
    page = _to_array(image)
    if deskew:
        page = _deskew(page)
    if binarize or remove_lines:
        _, page = cv2.threshold(page, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if remove_lines:
        page = _remove_table_lines(page)
    return Image.fromarray(page)


def _png(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG", dpi=(RENDER_DPI, RENDER_DPI))
    return buf.getvalue()


# --- ориентация ---


def parse_osd(text):
    """``(rotate, confidence)`` from Tesseract's ``--psm 0`` report, or None.

    ``rotate`` is how many degrees clockwise the page has to turn to stand
    upright."""
    rotate = confidence = None
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key = key.strip().lower()
        try:
            if key == "rotate":
                rotate = int(value.strip())
            elif key == "orientation confidence":
                confidence = float(value.strip())
        except ValueError:
            return None
    if rotate is None or confidence is None:
        return None
    return rotate, confidence


def _osd_rotation(image):
    """Degrees clockwise to turn the page upright, or None when OSD can't say."""
    try:
        out = _run(
            _base_args() + ["stdin", "stdout"] + _tessdata_args()
            + ["--psm", "0", "--dpi", str(RENDER_DPI)],
            _png(image),
        )
    except (OSError, subprocess.SubprocessError):
        # Нет osd.traineddata или слишком мало текста на странице — оба
        # случая означают «не знаю», а не ошибку.
        return None
    parsed = parse_osd(out)
    if parsed is None:
        return None
    rotate, confidence = parsed
    return rotate if confidence >= OSD_MIN_CONFIDENCE else None


def _turned(image, clockwise):
    # PIL turns counter-clockwise for a positive angle.
    return image if clockwise % 360 == 0 else image.rotate(-clockwise, expand=True)


# --- распознавание ---


def parse_tsv(text):
    """Words from Tesseract's TSV output: one ``Word`` per recognised word
    (level 5), its vertical centre and horizontal extent in pixels."""
    words = []
    lines = text.splitlines()
    if not lines:
        return words
    header = lines[0].split("\t")
    try:
        index = {name: header.index(name) for name in
                 ("level", "left", "top", "width", "height", "conf", "text")}
    except ValueError:
        return words
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) < len(header):
            continue
        if cells[index["level"]] != "5":
            continue
        word = cells[index["text"]].strip()
        if not word:
            continue
        try:
            left = float(cells[index["left"]])
            top = float(cells[index["top"]])
            width = float(cells[index["width"]])
            height = float(cells[index["height"]])
        except ValueError:
            continue
        words.append(Word(
            y=top + height / 2, x0=left, x1=left + width, height=height, text=word,
        ))
    return words


def _recognize(image):
    out = _run(
        _base_args() + ["stdin", "stdout"] + _tessdata_args()
        + ["-l", LANGUAGES, "--psm", str(page_segmentation_mode()),
           "--dpi", str(RENDER_DPI), "tsv"],
        _png(image),
    )
    return parse_tsv(out)


def _text_length(words):
    return sum(len(word.text) for word in words)


def recognize_page(data: bytes):
    """``(words, page)`` — positioned words for one page image, read
    whichever way up it is, and the prepared page they were read from,
    turned upright: the words' coordinates are on that image, which is what
    ``read_region`` needs to read a cell again.

    ``([], None)`` when Tesseract isn't available, the image can't be read,
    or recognition fails or runs out of time.
    """
    if not available():
        return [], None
    try:
        with Image.open(io.BytesIO(data)) as source:
            page = preprocess(source.convert("RGB"))
        rotation = _osd_rotation(page)
        if rotation is not None:
            upright = _turned(page, rotation)
            words = _recognize(upright)
        else:
            words, upright = [], page
            for angle in ROTATIONS:
                turned = _turned(page, angle)
                attempt = _recognize(turned)
                if _text_length(attempt) >= READS_PROPERLY:
                    words, upright = attempt, turned
                    break
                if len(attempt) > len(words):
                    words, upright = attempt, turned
        return ocr_lines.normalize_words(words), upright
    except subprocess.TimeoutExpired:
        logger.warning("Tesseract: страница не распознана за %s с", timeout_seconds())
        return [], None
    except Exception:
        logger.exception("Tesseract OCR failed")
        return [], None


def recognize_page_words(data: bytes) -> list:
    """Positioned words for one page image, read whichever way up it is —
    the same contract as ``win_ocr.recognize_page_words``.

    Empty when Tesseract isn't available, the image can't be read, or
    recognition fails or runs out of time.
    """
    return recognize_page(data)[0]


# Margin around a cell read again, in pixels at RENDER_DPI — a cell's own
# border must stay outside, the strokes of its digits inside.
REGION_PADDING = 6


def read_region(page, box, whitelist=None) -> str:
    """The text of one region of a prepared page, read as a single line
    (``--psm 7``) — for a cell whose value the whole-page reading missed.

    ``box`` is ``(x0, y0, x1, y1)`` in the page's pixels; ``whitelist`` the
    only characters allowed in the answer ("0123456789%,." for a rate), or
    None for free text. Empty when nothing could be read.
    """
    if page is None or not available():
        return ""
    x0, y0, x1, y1 = box
    x0 = max(int(x0) - REGION_PADDING, 0)
    y0 = max(int(y0) - REGION_PADDING, 0)
    x1 = min(int(x1) + REGION_PADDING, page.width)
    y1 = min(int(y1) + REGION_PADDING, page.height)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return ""
    args = (
        _base_args() + ["stdin", "stdout"] + _tessdata_args()
        + ["-l", LANGUAGES, "--psm", "7", "--dpi", str(RENDER_DPI)]
    )
    if whitelist:
        args += ["-c", f"tessedit_char_whitelist={whitelist}"]
    try:
        text = _run(args, _png(page.crop((x0, y0, x1, y1))))
    except subprocess.TimeoutExpired:
        logger.warning("Tesseract: участок страницы не прочитан за %s с", timeout_seconds())
        return ""
    except (OSError, subprocess.SubprocessError):
        logger.exception("Tesseract: участок страницы не прочитан")
        return ""
    return " ".join(ocr_lines.normalize_text(part) for part in text.split())


def recognize_text(images: list) -> list:
    """One string per image, its lines top to bottom — the same shape as
    ``win_ocr.recognize_text``."""
    return ["\n".join(ocr_lines.group_into_lines(recognize_page_words(data))) for data in images]
