import io
from urllib.parse import unquote

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
    slug = unquote(project_url.rstrip("/").rsplit("/", 1)[-1])

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
