import logging
import os
import secrets
from logging.config import dictConfig
from pathlib import Path

from flask import Flask
from flask_wtf import CSRFProtect

csrf = CSRFProtect()

# A generous ceiling for the whole request body — an estimate can legitimately
# run tens of megabytes, but nothing the program accepts needs more than
# this, and openpyxl loads a workbook into memory whole, so an unbounded
# upload is an unbounded memory allocation.
MAX_CONTENT_LENGTH = 60 * 1024 * 1024

# The three logger.info() calls in this codebase are audit trail, not noise
# ("a section quietly going missing can be traced", "if a figure on the page
# later raises a question, this shows what the program actually got from the
# file") — but with no handler configured anywhere, Python's logging module
# defaults every logger to WARNING and drops them silently. INFO is the floor
# this app needs, not a verbosity choice.
LOG_LEVEL = os.environ.get("KEYPARAMS_LOG_LEVEL", "INFO")


def _configure_logging(projects_root):
    """A rotating file handler for every logger under ``app.*``.

    Skipped under pytest (``PYTEST_CURRENT_TEST`` is set for the duration of
    every test) and once a handler is already attached: ``create_app`` runs
    once per real process but many times per test session, each call with
    its own throwaway ``tmp_path`` — reconfiguring logging, and opening a log
    file, on every one of those would leave file handles pinned in temporary
    directories pytest is trying to clean up, exactly the kind of
    Windows-file-still-open problem this codebase already works around
    elsewhere (see ``storage.delete_project``).
    """
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    if logging.getLogger("app").handlers:
        return

    log_dir = Path(os.environ.get("KEYPARAMS_LOG_DIR") or projects_root.parent / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(levelname)s %(name)s [%(threadName)s]: %(message)s",
            },
        },
        "handlers": {
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(log_dir / "keyparams.log"),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
                "formatter": "default",
                "level": LOG_LEVEL,
            },
        },
        "loggers": {
            "app": {"handlers": ["file"], "level": LOG_LEVEL, "propagate": False},
            "werkzeug": {"handlers": ["file"], "level": "WARNING", "propagate": False},
        },
    })


def _default_projects_root():
    """Where project data lives when nothing else says so — never inside the
    code tree, where a clean checkout or a stray ``git clean`` could take it
    out with everything else that isn't meant to survive one. This is only
    the out-of-the-box fallback; a real deployment sets ``KEYPARAMS_PROJECTS_ROOT``
    to wherever its data actually belongs (a dedicated volume, typically),
    and that always wins over this.
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "KeyParams" / "storage" / "projects"


def _persisted_secret_key(projects_root):
    """A signing key that survives process restarts — generated once, then
    reused, rather than fresh on every ``create_app()`` call. A key that
    changes on every restart (including the debug reloader's, mid-development)
    would invalidate every CSRF token already handed to an open browser tab
    the moment the process restarted.
    """
    path = projects_root.parent / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding="utf-8")
    return key


def _secret_key(projects_root):
    """The key CSRF tokens (and Flask's session cookie) are signed with.

    ``KEYPARAMS_SECRET_KEY`` always wins — the only sane choice once more
    than one process serves the same app. Under pytest a fresh in-memory key
    is enough (nothing restarts mid-test, and persisting one would litter
    pytest's shared temp root with a file next to every test's own
    throwaway ``tmp_path``); everywhere else the key is persisted next to
    the project data so it survives a restart.
    """
    key = os.environ.get("KEYPARAMS_SECRET_KEY")
    if key:
        return key
    if "PYTEST_CURRENT_TEST" in os.environ:
        return secrets.token_hex(32)
    return _persisted_secret_key(projects_root)


def create_app(projects_root=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.config["PROJECTS_ROOT"] = Path(
        projects_root
        or os.environ.get("KEYPARAMS_PROJECTS_ROOT")
        or _default_projects_root()
    )
    app.config["SECRET_KEY"] = _secret_key(app.config["PROJECTS_ROOT"])
    # Eleven mutating POST routes were plain forms with no CSRF token — a
    # request forged from any other tab in the same browser (the slug is
    # just the project's own name, easy to guess) could delete a project or
    # overwrite its hand-entered coefficients. Disabled under pytest: the
    # test client is trusted code, not a browser a form could be forged
    # from, and requiring a token on every one of hundreds of existing
    # ``client.post(...)`` calls would test the library, not this app.
    app.config["WTF_CSRF_ENABLED"] = "PYTEST_CURRENT_TEST" not in os.environ
    csrf.init_app(app)
    _configure_logging(app.config["PROJECTS_ROOT"])

    from . import excel_report_routes, routes
    app.register_blueprint(routes.bp)
    app.register_blueprint(excel_report_routes.excel_report_bp)

    return app
