"""Логин и пароль на всё приложение — один список пользователей, без ролей
и без самостоятельной регистрации: добавляет их только тот, у кого уже
есть доступ к серверу (см. ``create_user`` — вызывается из кода, не с
веб-страницы, ровно как и первый пользователь программы).

Хранится рядом с данными проектов (``projects_root.parent / "users.json"``),
тем же способом, что и ``secret_key`` в ``app/__init__.py`` — переживает
пересборку и перезапуск контейнера, потому что живёт в примонтированном
томе, а не в самом образе.
"""

import json
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash


def _users_path(projects_root: Path) -> Path:
    return projects_root.parent / "users.json"


def _normalize(username: str) -> str:
    """Логин без разницы в регистре — «Erokhov» и «erokhov» это один и тот
    же вход, а не два разных аккаунта из-за опечатки в Caps Lock."""
    return (username or "").strip().lower()


def load_users(projects_root: Path) -> dict:
    """``{логин: хэш пароля}``. Пустой словарь, если файла ещё нет или его
    не удалось прочитать — тогда войти не может никто, а не «кто угодно»."""
    path = _users_path(projects_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_users(projects_root: Path, users: dict) -> None:
    path = _users_path(projects_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def create_user(projects_root: Path, username: str, password: str) -> None:
    """Создаёт пользователя или меняет пароль существующему — тем же
    вызовом: второй ``create_user`` с тем же логином просто перезаписывает
    хэш, не требуя отдельной функции «сменить пароль»."""
    users = load_users(projects_root)
    users[_normalize(username)] = generate_password_hash(password)
    save_users(projects_root, users)


def verify_login(projects_root: Path, username: str, password: str) -> bool:
    users = load_users(projects_root)
    hashed = users.get(_normalize(username))
    if hashed is None:
        return False
    return check_password_hash(hashed, password)
