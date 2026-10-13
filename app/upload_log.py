"""Журнал загрузок — обычный текстовый файл: какие объекты созданы и
обновлены, каким файлом, кем и когда.

Пишется при каждой успешной загрузке данных по проектам: импорт из сводного
файла, новый проект, замена документа в проекте (ДГП, ТЗ, смета, протокол,
удорожание, прогноз, обложка). Отклонённая загрузка в журнал не попадает:
ничего не изменилось.

Лежит рядом с папкой проектов, а не в ней (на сервере это том /data) — так
он переживает пересборку контейнера и уходит в резервные копии вместе с
данными, как и журнал распознаваний (``app/corrections.py``). Новые записи
дописываются в конец.

Открыть его из программы может только аккаунт из ``READERS`` — кнопка
«Информация о загрузках» в окне «Настройки».
"""

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

FILE_NAME = "upload_log.txt"

# Логины, которым журнал виден, — в том же виде, в каком их хранит
# ``auth`` (без разницы в регистре).
READERS = {"erokhov"}

# Москва живёт на UTC+3 без перехода на летнее время — фиксированный сдвиг
# не зависит от того, есть ли в системе база часовых поясов.
MOSCOW = timezone(timedelta(hours=3))

_lock = threading.Lock()


def log_path(root) -> Path:
    return Path(root).parent / FILE_NAME


def can_read(user) -> bool:
    return (user or "").strip().lower() in READERS


def record(root, user, title, lines=(), now=None) -> None:
    """Дописать одну запись: строка с датой, пользователем и тем, что
    случилось, и под ней — подробности с отступом."""
    moment = (now or datetime.now(timezone.utc)).astimezone(MOSCOW)
    text = f"{moment:%d.%m.%Y %H:%M} МСК · {user or '—'} · {title}\n"
    text += "".join(f"    {line}\n" for line in lines)
    path = log_path(root)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def read(root) -> str:
    path = log_path(root)
    return path.read_text(encoding="utf-8") if path.exists() else ""
