import io
from datetime import datetime, timedelta, timezone

from app import create_app, storage, upload_log
from tests.test_master_import_routes import _workbook_bytes
from tests.test_routes import (
    _dgp_bytes, _make_project_with_passport, _smeta_bytes, _tz_bytes, _upload_estimate,
)


def _log_text(root):
    path = upload_log.log_path(root)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _root(tmp_path):
    # Журнал лежит в папке над папкой проектов — у каждого теста своя.
    return tmp_path / "projects"


def _login(client, user):
    with client.session_transaction() as session:
        session["user"] = user


def test_record_writes_a_dated_plain_text_entry(tmp_path):
    moment = datetime(2026, 10, 13, 13, 5, tzinfo=timezone.utc)

    upload_log.record(tmp_path / "projects", "erokhov", "Импорт из сводного файла «a.xlsx»",
                      ["Создано: 1", "+ CITY BAY 5"], now=moment)

    text = _log_text(tmp_path / "projects")
    # Moscow time, UTC+3.
    assert text.startswith("13.10.2026 16:05 МСК · erokhov · Импорт из сводного файла «a.xlsx»\n")
    assert "    + CITY BAY 5\n" in text
    assert upload_log.log_path(tmp_path / "projects").suffix == ".txt"


def test_master_import_logs_created_and_updated_objects(tmp_path):
    app = create_app(_root(tmp_path))
    client = app.test_client()
    _login(client, "erokhov")
    data = _workbook_bytes("MIRA", None, "Бизнес", "АНТТЕК", (1.0, 2.0, 3.0))

    for _ in range(2):
        client.post("/master-import",
                    data={"workbook_file": (io.BytesIO(data), "portfolio.xlsx")},
                    content_type="multipart/form-data")

    text = _log_text(_root(tmp_path))
    assert text.count("Импорт из сводного файла «portfolio.xlsx»") == 2
    assert "Создано: 1, обновлено: 0" in text
    assert "Создано: 0, обновлено: 1" in text
    assert "+ создан: MIRA" in text
    assert "~ обновлён: MIRA" in text
    assert "· erokhov ·" in text


def test_creating_a_project_is_logged_with_its_files(tmp_path):
    app = create_app(_root(tmp_path))
    client = app.test_client()

    resp = client.post("/projects", data={
        "project_name": "Новый объект",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(_smeta_bytes()), "smeta.xlsx"),
    }, content_type="multipart/form-data")

    assert resp.status_code == 302
    text = _log_text(_root(tmp_path))
    assert "Новый проект «Новый объект»" in text
    assert "ДГП: dgp.docx" in text
    assert "Смета: smeta.xlsx" in text


def test_replacing_a_file_in_a_project_is_logged_as_an_update(tmp_path):
    app = create_app(_root(tmp_path))
    client = app.test_client()
    slug = _make_project_with_passport(_root(tmp_path), "Объект")

    resp = _upload_estimate(client, slug, _smeta_bytes(), "новая смета.xlsx")

    assert resp.status_code == 302
    text = _log_text(_root(tmp_path))
    assert "Проект «Объект» обновлён" in text
    assert "Смета: новая смета.xlsx" in text


def test_a_rejected_upload_is_not_logged(tmp_path):
    app = create_app(_root(tmp_path))
    client = app.test_client()
    slug = _make_project_with_passport(_root(tmp_path), "Объект")

    _upload_estimate(client, slug, b"not an xlsx", "плохой.xlsx")

    assert _log_text(_root(tmp_path)) == ""


def test_only_erokhov_can_open_the_upload_log(tmp_path):
    app = create_app(_root(tmp_path))
    upload_log.record(_root(tmp_path), "erokhov", "Проект «А» обновлён", ["Смета: a.xlsx"])
    client = app.test_client()

    _login(client, "guest")
    assert client.get("/upload-log").status_code == 404
    assert 'id="upload-log-button"' not in client.get("/").get_data(as_text=True)

    _login(client, "Erokhov")
    resp = client.get("/upload-log")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    assert "Проект «А» обновлён" in resp.get_data(as_text=True)
    assert 'id="upload-log-button"' in client.get("/").get_data(as_text=True)

    download = client.get("/upload-log?download=1")
    assert "attachment" in download.headers["Content-Disposition"]
