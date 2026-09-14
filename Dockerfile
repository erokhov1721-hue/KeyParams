# syntax=docker/dockerfile:1
#
# Образ для Linux (см. README.md, раздел «Docker», за объяснением, чего это
# стоит по сравнению с родным запуском на Windows): распознавание сканов
# идёт через EasyOCR, а не через быстрый и точный по кириллице Windows OCR
# (тот пакет winocr вообще не ставится — он привязан к Windows, см. маркер
# sys_platform == "win32" в requirements.txt), и PDF использует не настоящий
# Arial, а его замену со схожими метриками.
FROM python:3.14-slim

# fonts-dejavu-core — замена Arial для PDF (app/pdf_export.py грузит файлы
#   arial.ttf/arialbd.ttf по пути KEYPARAMS_FONT_DIR; настоящего Arial на
#   Linux нет, а DejaVu Sans бесплатен, уже используется matplotlib-графиками
#   на этой же странице и полностью покрывает кириллицу);
# libglib2.0-0 — нужна opencv-python-headless (тянет easyocr), без неё
#   некоторые сборки падают при импорте уже на этапе `import cv2`;
# curl — только для HEALTHCHECK ниже.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# torch отдельным слоем и с чужого индекса — PyPI по умолчанию отдаёт сборку
# с CUDA (несколько лишних гигабайт), которая тут не нужна: OCR всегда идёт
# на CPU (см. app/ocr.py, gpu=False), GPU в контейнере не будет. Версию не
# фиксируем сами — берём ту, что попросит easyocr из requirements.txt ниже;
# раз она уже стоит и удовлетворяет требованию, pip её не переставит.
RUN pip install --no-cache-dir torch torchvision \
        --index-url https://download.pytorch.org/whl/cpu

# Открытые диапазоны версий, не requirements-lock.txt: тот зафиксирован по
# `pip freeze` на Windows и содержит строки вроде winocr/winrt-*, у которых
# на Linux нет колеса вовсе — pip install на них тут же упадёт. Сам образ,
# после сборки, и есть тот самый «зафиксированный набор версий» — только
# уже для Linux.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py .

# Arial под тем же именем, что ждёт app/pdf_export.py — см. переменную
# KEYPARAMS_FONT_DIR ниже. Правится в одном месте, а не двух: код продолжает
# искать ровно "arial.ttf"/"arialbd.ttf", как и на Windows.
RUN mkdir -p /app/fonts \
    && cp /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf /app/fonts/arial.ttf \
    && cp /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf /app/fonts/arialbd.ttf

# Не root: том /data и домашний каталог принадлежат этому пользователю
# заранее, а не создаются от имени root при первом запуске.
RUN useradd --create-home --uid 1000 keyparams \
    && mkdir -p /data/projects /data/easyocr-models \
    && chown -R keyparams:keyparams /data /app

USER keyparams

ENV KEYPARAMS_ENV=production \
    KEYPARAMS_HOST=0.0.0.0 \
    KEYPARAMS_PORT=8080 \
    KEYPARAMS_PROJECTS_ROOT=/data/projects \
    KEYPARAMS_FONT_DIR=/app/fonts \
    EASYOCR_MODULE_PATH=/data/easyocr-models
# KEYPARAMS_SECRET_KEY, ANTHROPIC_API_KEY и OCR_FALLBACK_ENABLED — не отсюда:
# первый должен быть одинаковым при перезапуске/масштабировании, второй —
# секрет, а третий — осознанный выбор оператора (EasyOCR на CPU — это минуты
# на объект, поэтому выключен по умолчанию даже на Linux, как и на Windows,
# см. app/passport.py). Все три — через `docker run -e ...` / compose,
# см. README.md.

EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://127.0.0.1:8080/ || exit 1

CMD ["python", "run.py"]
