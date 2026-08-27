import logging
import os
from pathlib import Path

from app import _configure_logging, _default_projects_root, create_app


def _reset_app_logger():
    app_logger = logging.getLogger("app")
    for handler in list(app_logger.handlers):
        handler.close()
        app_logger.removeHandler(handler)


def test_configure_logging_writes_info_level_records_to_a_rotating_file(tmp_path, monkeypatch):
    # PYTEST_CURRENT_TEST is what keeps _configure_logging a no-op during the
    # rest of the test suite (see its own docstring) — cleared here so this
    # one test can see it actually run.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    _reset_app_logger()
    try:
        projects_root = tmp_path / "storage" / "projects"
        _configure_logging(projects_root)

        logger = logging.getLogger("app.something")
        assert logger.getEffectiveLevel() <= logging.INFO
        logger.info("проверочная запись")

        log_file = tmp_path / "storage" / "logs" / "keyparams.log"
        assert log_file.exists()
        assert "проверочная запись" in log_file.read_text(encoding="utf-8")
    finally:
        _reset_app_logger()


def test_configure_logging_is_a_no_op_under_pytest(tmp_path):
    # The real guard this test exercises: PYTEST_CURRENT_TEST is set for the
    # entire test session, so a plain call here must not touch the logger or
    # the filesystem at all.
    assert "PYTEST_CURRENT_TEST" in os.environ
    _reset_app_logger()

    _configure_logging(tmp_path / "storage" / "projects")

    assert logging.getLogger("app").handlers == []
    assert not (tmp_path / "storage" / "logs").exists()


# --- где по умолчанию лежат данные проектов ---

def test_default_projects_root_follows_localappdata(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Кто-то\AppData\Local")

    root = _default_projects_root()

    assert root == Path(r"C:\Users\Кто-то\AppData\Local\KeyParams\storage\projects")


def test_default_projects_root_falls_back_to_home_without_localappdata(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    root = _default_projects_root()

    assert root == Path.home() / "KeyParams" / "storage" / "projects"


def test_default_projects_root_is_never_inside_the_code_tree():
    repo_root = Path(__file__).resolve().parent.parent

    root = _default_projects_root()

    assert repo_root not in root.parents


def test_create_app_prefers_an_explicit_projects_root(tmp_path, monkeypatch):
    monkeypatch.setenv("KEYPARAMS_PROJECTS_ROOT", str(tmp_path / "from-env"))

    app = create_app(tmp_path / "from-argument")

    assert app.config["PROJECTS_ROOT"] == tmp_path / "from-argument"


def test_create_app_falls_back_to_the_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("KEYPARAMS_PROJECTS_ROOT", str(tmp_path / "from-env"))

    app = create_app()

    assert app.config["PROJECTS_ROOT"] == tmp_path / "from-env"


def test_create_app_falls_back_to_the_default_outside_the_repo(monkeypatch):
    monkeypatch.delenv("KEYPARAMS_PROJECTS_ROOT", raising=False)

    app = create_app()

    assert app.config["PROJECTS_ROOT"] == _default_projects_root()
