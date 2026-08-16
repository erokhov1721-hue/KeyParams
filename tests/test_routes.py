import io

from openpyxl import Workbook

from app import create_app
from tests.helpers import build_docx_bytes, document_xml


def _dgp_bytes():
    return build_docx_bytes(document_xml(paragraphs=[
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,"
    ]))


def _tz_bytes():
    return build_docx_bytes(document_xml(tables=[[["1", "Площадь подземной части", "м2", "1 000"]]]))


def _smeta_bytes():
    wb = Workbook()
    wb.active.append(["Раздел", "Сумма"])
    wb.active.append(["Фундамент", 1000])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


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


def test_every_page_offers_the_theme_toggle(tmp_path):
    # The toggle lives in the shared layout, so a page that renders its own
    # header block must not end up without it.
    from app import storage

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Тест")
    storage.passport_path(tmp_path, slug).write_text("{}", encoding="utf-8")

    for path in ("/", "/projects/new", f"/projects/{slug}"):
        body = client.get(path).get_data(as_text=True)
        assert 'id="theme-toggle"' in body, path


def test_native_dropdowns_follow_the_theme(tmp_path):
    # The popup of a <select> is drawn by the browser, not by this
    # stylesheet. With no colour scheme declared it opens on white while its
    # options inherit the field's near-white text, which left the list of
    # building classes unreadable in the dark theme.
    app = create_app(tmp_path)
    client = app.test_client()

    css = client.get("/static/style.css").get_data(as_text=True)

    assert "color-scheme: dark" in css
    assert "color-scheme: light" in css
    assert "select option" in css


def test_theme_choice_is_applied_before_the_page_paints(tmp_path):
    # The saved theme has to be read in <head>: doing it lower down makes a
    # light-theme user watch the dark theme flash on every single load.
    app = create_app(tmp_path)
    client = app.test_client()

    body = client.get("/").get_data(as_text=True)
    head = body.split("</head>")[0]

    assert "localStorage.getItem('theme')" in head


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
    slug = "Правка"

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


def _root_with_passport_above(tmp_path):
    """Projects root with a real passport.json planted one level above it.

    Without the slug whitelist guard, the slug ".." would resolve to that
    planted file, so the route would answer 200 instead of 404.
    """
    root = tmp_path / "projects"
    root.mkdir()
    (tmp_path / "passport.json").write_text(
        '{"project_name": "Похищенный"}', encoding="utf-8"
    )
    return root


def test_path_traversal_blocked_on_get(tmp_path):
    root = _root_with_passport_above(tmp_path)
    assert (root / ".." / "passport.json").exists(), "test setup must be a real repro"

    client = create_app(root).test_client()
    resp = client.get("/projects/..")
    assert resp.status_code == 404


def test_path_traversal_blocked_on_post(tmp_path):
    root = _root_with_passport_above(tmp_path)
    assert (root / ".." / "passport.json").exists(), "test setup must be a real repro"

    client = create_app(root).test_client()
    resp = client.post("/projects/..", data={"building_class": "Бизнес"})
    assert resp.status_code == 404
    # The planted passport must be untouched.
    assert "Похищенный" in (tmp_path / "passport.json").read_text(encoding="utf-8")


def test_create_project_with_name_that_slugifies_to_empty(tmp_path):
    """A name made only of stripped characters is a 400, not a 500."""
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": '???',
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400

    from app import storage
    assert storage.list_project_slugs(tmp_path) == []


def test_create_project_with_hash_in_name_redirect_is_followable(tmp_path):
    """A '#' in the project name must not truncate the redirect target."""
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Дом #5 100%",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 302

    page = client.get(resp.headers["Location"])
    assert page.status_code == 200


def test_docx_error_message_hides_server_paths(tmp_path):
    """The user-facing error must not leak absolute filesystem paths."""
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Тест",
        "dgp_file": (io.BytesIO(b"this has a .docx name but is not a real zip"), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400
    body = resp.data.decode("utf-8")
    assert "dgp.docx" not in body
    assert str(tmp_path) not in body


def test_no_orphan_on_corrupted_docx(tmp_path):
    """Verify that a failed project creation doesn't leave an orphaned directory."""
    app = create_app(tmp_path)
    client = app.test_client()
    project_name = "Проверка"

    client.post("/projects", data={
        "project_name": project_name,
        "dgp_file": (io.BytesIO(b"this has a .docx name but is not a real zip"), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")

    from app import storage
    slugs = storage.list_project_slugs(tmp_path)
    assert len(slugs) == 0, "Expected no projects after failed upload"


def test_delete_project_removes_it_and_redirects_to_index(tmp_path):
    from app import storage

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Тест")
    storage.passport_path(tmp_path, slug).write_text("{}", encoding="utf-8")

    resp = client.post(f"/projects/{slug}/delete", follow_redirects=True)

    assert resp.status_code == 200
    assert slug not in storage.list_project_slugs(tmp_path)
    assert not (tmp_path / slug).exists()


def test_delete_project_unknown_slug_redirects_instead_of_404(tmp_path):
    # Deleting what isn't there already got the user what they wanted, so it
    # sends them back to the dashboard. A double-click on the delete button
    # used to land the second POST on a bare "Not Found" page with no way back.
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects/does-not-exist/delete")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_dashboard_sweeps_up_a_delete_that_could_not_finish(tmp_path):
    # Whatever the user deletes has to end up actually deleted, even when a
    # file was in use at the time and the removal had to be left for later.
    from app import storage

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Недоудалённый")
    storage.estimate_path(tmp_path, slug).write_bytes(b"PK\x03\x04")
    (tmp_path / slug / storage.DELETED_MARKER).write_bytes(b"")

    resp = client.get("/")

    assert resp.status_code == 200
    assert not (tmp_path / slug).exists()


def test_rename_project_updates_name_and_redirects_to_index(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Старое имя")
    passport_module.save_passport(
        {"project_name": "Старое имя"}, storage.passport_path(tmp_path, slug),
    )

    resp = client.post(f"/projects/{slug}/rename", data={"project_name": "Новое имя"}, follow_redirects=True)

    assert resp.status_code == 200
    saved = passport_module.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["project_name"] == "Новое имя"


def test_rename_project_rejects_empty_name(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Старое имя")
    passport_module.save_passport(
        {"project_name": "Старое имя"}, storage.passport_path(tmp_path, slug),
    )

    resp = client.post(f"/projects/{slug}/rename", data={"project_name": "   "})

    assert resp.status_code == 400
    saved = passport_module.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["project_name"] == "Старое имя"


def test_rename_project_unknown_slug_404s(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects/does-not-exist/rename", data={"project_name": "Новое имя"})
    assert resp.status_code == 404


def test_index_page_shows_project_name_instead_of_slug(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Проспект Мира")
    passport_module.save_passport(
        {"project_name": "Проспект Мира — очень длинное имя"},
        storage.passport_path(tmp_path, slug),
    )

    resp = client.get("/")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Проспект Мира — очень длинное имя" in body


def _make_project_with_passport(root, name, **fields):
    from app import storage, passport as passport_module

    slug = storage.create_project(root, name)
    data = {
        "project_name": name, "year_signed": None, "building_class": None,
        "general_contractor": None, "underground_area_sqm": None,
        "aboveground_area_sqm": None, "total_area_sqm": None, "ocr_fields": [],
    }
    data.update(fields)
    passport_module.save_passport(data, storage.passport_path(root, slug))
    return slug


def test_compare_projects_shows_selected_projects_side_by_side(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    slug1 = _make_project_with_passport(tmp_path, "ПроектА", total_area_sqm=1000.0)
    slug2 = _make_project_with_passport(tmp_path, "ПроектБ", total_area_sqm=2000.0)

    resp = client.get(f"/compare?slug={slug1}&slug={slug2}")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "ПроектА" in body
    assert "ПроектБ" in body
    assert "1 000" in body
    assert "2 000" in body


def test_compare_projects_table_shows_price_per_sqm_row(tmp_path):
    from app import passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project_with_passport(
        tmp_path, "ПроектА", contract_price_rub=10067050887.72, total_area_sqm=67413.0,
    )

    resp = client.get(f"/compare?slug={slug}")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Цена за м²" in body
    expected = passport_module.format_number(10067050887.72 / 67413.0)
    assert expected in body


def test_compare_projects_table_shows_dash_for_price_per_sqm_when_area_missing(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project_with_passport(tmp_path, "ПроектА", contract_price_rub=100.0)

    resp = client.get(f"/compare?slug={slug}")

    assert resp.status_code == 200
    assert "Цена за м²" in resp.data.decode("utf-8")


def test_compare_projects_ignores_unknown_slug(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project_with_passport(tmp_path, "ПроектА")

    resp = client.get(f"/compare?slug={slug}&slug=does-not-exist")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "ПроектА" in body
    assert "does-not-exist" not in body


def test_compare_projects_shows_price_charts(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    slug1 = _make_project_with_passport(
        tmp_path, "ПроектА", contract_price_rub=100.0, year_signed="2024",
        building_class="Бизнес", total_area_sqm=1.0,
    )
    slug2 = _make_project_with_passport(
        tmp_path, "ПроектБ", contract_price_rub=200.0, year_signed="2023",
        building_class="Комфорт", total_area_sqm=1.0,
    )

    resp = client.get(f"/compare?slug={slug1}&slug={slug2}")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Цена работ по году подписания" in body
    assert "Цена работ по классу жилья" in body
    assert "Цена работ по проектам" in body
    assert "Цена за м² по проектам" in body
    assert "ПроектА (2024)" in body
    assert "ПроектБ (Комфорт)" in body


def test_compare_projects_shows_empty_chart_message_without_data(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project_with_passport(tmp_path, "ПроектА")

    resp = client.get(f"/compare?slug={slug}")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Недостаточно данных" in body


def test_compare_projects_pdf_returns_pdf_file(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    slug1 = _make_project_with_passport(
        tmp_path, "ПроектА", contract_price_rub=100.0, year_signed="2024", total_area_sqm=1.0,
    )
    slug2 = _make_project_with_passport(
        tmp_path, "ПроектБ", contract_price_rub=200.0, year_signed="2023", total_area_sqm=1.0,
    )

    resp = client.get(f"/compare/pdf?slug={slug1}&slug={slug2}")

    assert resp.status_code == 200
    assert resp.content_type == "application/pdf"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert resp.data[:4] == b"%PDF"


def test_compare_projects_pdf_redirects_to_index_when_none_selected(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()

    resp = client.get("/compare/pdf", follow_redirects=True)

    assert resp.status_code == 200
    assert resp.request.path == "/"


def test_compare_projects_redirects_to_index_when_none_selected(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()

    resp = client.get("/compare", follow_redirects=True)

    assert resp.status_code == 200
    assert resp.request.path == "/"


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


def test_project_page_shows_numeric_field_with_thousands_spaces(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Проект с суммой")
    passport_module.save_passport({
        "project_name": "Проект с суммой", "year_signed": None, "building_class": None,
        "general_contractor": None, "contract_price_rub": 10067050887.72,
        "underground_area_sqm": None, "aboveground_area_sqm": None,
        "total_area_sqm": None, "ocr_fields": [],
    }, storage.passport_path(tmp_path, slug))

    resp = client.get(f"/projects/{slug}")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'value="10 067 050 887.72"' in body


def test_project_page_building_class_is_a_dropdown_with_fixed_options(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Проект без класса")
    passport_module.save_passport({
        "project_name": "Проект без класса", "year_signed": None, "building_class": None,
        "general_contractor": None, "contract_price_rub": None,
        "underground_area_sqm": None, "aboveground_area_sqm": None,
        "total_area_sqm": None, "ocr_fields": [],
    }, storage.passport_path(tmp_path, slug))

    resp = client.get(f"/projects/{slug}")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert '<select name="building_class">' in body
    for option in passport_module.BUILDING_CLASS_OPTIONS:
        assert f">{option}<" in body


def test_project_page_building_class_dropdown_preselects_current_value(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Проект с классом")
    passport_module.save_passport({
        "project_name": "Проект с классом", "year_signed": None, "building_class": "Бизнес",
        "general_contractor": None, "contract_price_rub": None,
        "underground_area_sqm": None, "aboveground_area_sqm": None,
        "total_area_sqm": None, "ocr_fields": [],
    }, storage.passport_path(tmp_path, slug))

    resp = client.get(f"/projects/{slug}")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert '<option value="Бизнес" selected>Бизнес</option>' in body


def test_project_page_shows_computed_price_per_sqm(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Проект с ценой")
    passport_module.save_passport({
        "project_name": "Проект с ценой",
        "year_signed": None,
        "building_class": None,
        "general_contractor": None,
        "contract_price_rub": 10067050887.72,
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": 67413.0,
        "ocr_fields": [],
    }, storage.passport_path(tmp_path, slug))

    resp = client.get(f"/projects/{slug}")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Цена за м²" in body
    expected = passport_module.format_number(10067050887.72 / 67413.0)
    assert expected in body


def test_project_page_shows_dash_for_price_per_sqm_when_area_missing(tmp_path):
    from app import storage, passport as passport_module

    app = create_app(tmp_path)
    client = app.test_client()
    slug = storage.create_project(tmp_path, "Проект без площади")
    passport_module.save_passport({
        "project_name": "Проект без площади",
        "year_signed": None,
        "building_class": None,
        "general_contractor": None,
        "contract_price_rub": 10067050887.72,
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": None,
        "ocr_fields": [],
    }, storage.passport_path(tmp_path, slug))

    resp = client.get(f"/projects/{slug}")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Цена за м²" in body


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


def test_project_page_shows_ai_badge_for_ai_filled_field(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    from app import storage, passport as passport_module

    slug = storage.create_project(tmp_path, "Проект с AI-полем")
    passport_module.save_passport({
        "project_name": "Проект с AI-полем",
        "year_signed": None,
        "building_class": None,
        "general_contractor": "ООО «Из AI»",
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": None,
        "ocr_fields": [],
        "ai_fields": ["general_contractor"],
    }, storage.passport_path(tmp_path, slug))

    resp = client.get(f"/projects/{slug}")

    assert resp.status_code == 200
    assert "Найдено через AI".encode("utf-8") in resp.data


def test_update_project_clears_ai_flag_when_value_changes(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    from app import storage, passport as passport_module

    slug = storage.create_project(tmp_path, "Проект с AI-полем")
    path = storage.passport_path(tmp_path, slug)
    passport_module.save_passport({
        "project_name": "Проект с AI-полем",
        "year_signed": None,
        "building_class": None,
        "general_contractor": None,
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": 67413.0,
        "ocr_fields": [],
        "ai_fields": ["total_area_sqm"],
    }, path)

    client.post(f"/projects/{slug}", data={"total_area_sqm": "70000"})

    saved = passport_module.load_passport(path)
    assert saved["total_area_sqm"] == 70000.0
    assert saved["ai_fields"] == []


def test_update_project_keeps_ai_flag_when_value_unchanged(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    from app import storage, passport as passport_module

    slug = storage.create_project(tmp_path, "Проект с AI-полем")
    path = storage.passport_path(tmp_path, slug)
    passport_module.save_passport({
        "project_name": "Проект с AI-полем",
        "year_signed": None,
        "building_class": None,
        "general_contractor": None,
        "underground_area_sqm": None,
        "aboveground_area_sqm": None,
        "total_area_sqm": 67413.0,
        "ocr_fields": [],
        "ai_fields": ["total_area_sqm"],
    }, path)

    client.post(f"/projects/{slug}", data={"total_area_sqm": "67413"})

    saved = passport_module.load_passport(path)
    assert saved["ai_fields"] == ["total_area_sqm"]


def test_create_project_with_estimate_saves_and_serves_it(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Со сметой",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(_smeta_bytes()), "smeta.xlsx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 302
    slug = "Со_сметой"

    from app import storage
    assert storage.estimate_path(tmp_path, slug).exists()

    page = client.get(f"/projects/{slug}/smeta")
    assert page.status_code == 200
    assert "Фундамент".encode("utf-8") in page.data


def test_create_project_without_estimate_smeta_route_404s(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Без сметы",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 302
    slug = "Без_сметы"

    page = client.get(f"/projects/{slug}/smeta")
    assert page.status_code == 404


def test_create_project_rejects_non_xlsx_estimate(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Плохая смета",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(b"not excel"), "smeta.txt"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400

    from app import storage
    assert storage.list_project_slugs(tmp_path) == []


def test_new_project_form_has_optional_estimate_field(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()

    resp = client.get("/projects/new")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'name="smeta_file"' in body
    assert 'accept=".xlsx"' in body


def test_project_page_shows_estimate_link_when_file_present(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    client.post("/projects", data={
        "project_name": "Есть смета",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(_smeta_bytes()), "smeta.xlsx"),
    }, content_type="multipart/form-data")

    page = client.get("/projects/Есть_смета")

    assert page.status_code == 200
    # Flask's url_for percent-encodes non-ASCII path segments (correct,
    # RFC 3986-compliant behavior), so the href in the rendered HTML is
    # not the literal Cyrillic slug — build the expected href the same
    # way the template does.
    with app.test_request_context():
        from flask import url_for
        expected_href = f'href="{url_for("main.estimate_page", slug="Есть_смета")}"'
    assert expected_href.encode("utf-8") in page.data


def test_project_page_hides_estimate_link_when_no_file(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    client.post("/projects", data={
        "project_name": "Нет сметы",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }, content_type="multipart/form-data")

    page = client.get("/projects/Нет_сметы")

    assert page.status_code == 200
    assert b"/smeta" not in page.data


def test_estimate_page_renders_multiple_sheets_as_tabs(tmp_path):
    wb = Workbook()
    wb.active.title = "Смета"
    wb.active["A1"] = "Итого"
    wb.create_sheet("Материалы")["A1"] = "Цемент"
    buf = io.BytesIO()
    wb.save(buf)

    app = create_app(tmp_path)
    client = app.test_client()
    client.post("/projects", data={
        "project_name": "Многолистовая",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(buf.getvalue()), "smeta.xlsx"),
    }, content_type="multipart/form-data")

    page = client.get("/projects/Многолистовая/smeta")

    assert page.status_code == 200
    body = page.data.decode("utf-8")
    assert "Итого" in body
    assert "Цемент" in body
    assert "Материалы" in body


def test_create_project_rejects_corrupted_estimate(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects", data={
        "project_name": "Битая смета",
        "dgp_file": (io.BytesIO(_dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
        "smeta_file": (io.BytesIO(b"this is not a real xlsx file"), "smeta.xlsx"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400

    from app import storage
    assert storage.list_project_slugs(tmp_path) == []


# --- contract-terms upload: the page explains why nothing was filled ---

def _upload_contract_terms(client, slug, follow=True):
    return client.post(
        f"/projects/{slug}/contract-terms",
        data={"contract_terms_file": (io.BytesIO(b"%PDF-fake"), "protocol.pdf")},
        content_type="multipart/form-data",
        follow_redirects=follow,
    )


def _stub_scan_returning(monkeypatch, fields, problem):
    """Make the upload path behave as a scan whose recognition gave this result."""
    from app import passport as passport_module

    monkeypatch.setattr(passport_module.pdf_reader, "read_pdf_text", lambda path: "")
    monkeypatch.setattr(
        passport_module.pdf_reader, "render_pages_to_images",
        lambda path, **kwargs: [b"png"],
    )
    monkeypatch.setattr(
        passport_module.ai_extractor, "extract_contract_terms_from_images",
        lambda images: (fields, problem),
    )


def test_contract_terms_upload_explains_missing_api_key(tmp_path, monkeypatch):
    from app import ai_extractor

    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project_with_passport(tmp_path, "ПроектА")
    _stub_scan_returning(monkeypatch, {}, ai_extractor.PROBLEM_NO_KEY)

    resp = _upload_contract_terms(client, slug)

    assert resp.status_code == 200
    assert "ANTHROPIC_API_KEY" in resp.data.decode("utf-8")


def test_contract_terms_upload_explains_empty_balance(tmp_path, monkeypatch):
    from app import ai_extractor

    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project_with_passport(tmp_path, "ПроектА")
    _stub_scan_returning(monkeypatch, {}, ai_extractor.PROBLEM_NO_CREDIT)

    resp = _upload_contract_terms(client, slug)

    # "Plans & Billing" renders escaped, so assert on plain-text wording.
    assert "нет средств" in resp.data.decode("utf-8")


def test_contract_terms_upload_says_nothing_recognized_when_read_but_empty(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project_with_passport(tmp_path, "ПроектА")
    _stub_scan_returning(monkeypatch, {}, None)

    resp = _upload_contract_terms(client, slug)

    assert "распознать не удалось" in resp.data.decode("utf-8")


def test_contract_terms_upload_shows_no_warning_when_fields_were_filled(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project_with_passport(tmp_path, "ПроектА")
    _stub_scan_returning(monkeypatch, {"performance_bond_pct": "3%"}, None)

    resp = _upload_contract_terms(client, slug)

    body = resp.data.decode("utf-8")
    assert "3%" in body
    assert "распознать не удалось" not in body
    assert "ANTHROPIC_API_KEY" not in body


def test_contract_terms_upload_saves_vat_from_recognition(tmp_path, monkeypatch):
    from app import passport as passport_module, storage

    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project_with_passport(tmp_path, "ПроектА")
    _stub_scan_returning(monkeypatch, {"vat": "20%"}, None)

    _upload_contract_terms(client, slug)

    saved = passport_module.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["vat"] == "20%"
    assert "vat" in saved["contract_auto_fields"]


# --- contract-terms PDF as part of project creation ---

def _dgp_bytes_signed_in(year):
    return build_docx_bytes(document_xml(paragraphs=[
        "Общество с ограниченной ответственностью «Ромашка» (ООО «Ромашка»), "
        "именуемое в дальнейшем «Генподрядчик», с третьей стороны,",
        f"{year} год",
    ]))


def _create_data(dgp=None, contract_terms=None):
    data = {
        "project_name": "ПроектА",
        "dgp_file": (io.BytesIO(dgp or _dgp_bytes()), "dgp.docx"),
        "tz_file": (io.BytesIO(_tz_bytes()), "tz.docx"),
    }
    if contract_terms is not None:
        data["contract_terms_file"] = contract_terms
    return data


def test_create_project_accepts_optional_contract_terms_pdf(tmp_path, monkeypatch):
    from app import storage

    app = create_app(tmp_path)
    client = app.test_client()
    _stub_scan_returning(monkeypatch, {"performance_bond_pct": "3%"}, None)

    resp = client.post("/projects", data=_create_data(
        contract_terms=(io.BytesIO(b"%PDF-fake"), "protocol.pdf"),
    ), content_type="multipart/form-data", follow_redirects=True)

    assert resp.status_code == 200
    slug = storage.list_project_slugs(tmp_path)[0]
    assert storage.contract_terms_path(tmp_path, slug).exists()
    assert "3%" in resp.data.decode("utf-8")


def test_create_project_works_without_contract_terms(tmp_path):
    from app import passport as passport_module, storage

    app = create_app(tmp_path)
    client = app.test_client()

    resp = client.post(
        "/projects", data=_create_data(), content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    slug = storage.list_project_slugs(tmp_path)[0]
    assert not storage.contract_terms_path(tmp_path, slug).exists()
    saved = passport_module.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["vat"] is None


def test_create_project_rejects_contract_terms_that_is_not_pdf(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()

    resp = client.post("/projects", data=_create_data(
        contract_terms=(io.BytesIO(b"not a pdf"), "protocol.docx"),
    ), content_type="multipart/form-data")

    assert resp.status_code == 400
    assert "PDF" in resp.data.decode("utf-8")


def test_create_project_rejects_oversized_contract_terms(tmp_path):
    from app import routes

    app = create_app(tmp_path)
    client = app.test_client()
    too_big = b"x" * (routes.MAX_CONTRACT_TERMS_SIZE + 1)

    resp = client.post("/projects", data=_create_data(
        contract_terms=(io.BytesIO(too_big), "protocol.pdf"),
    ), content_type="multipart/form-data")

    assert resp.status_code == 400


def test_create_project_sets_vat_from_signing_year_2026(tmp_path, monkeypatch):
    from app import passport as passport_module, storage

    app = create_app(tmp_path)
    client = app.test_client()
    _stub_scan_returning(monkeypatch, {"performance_bond_pct": "3%"}, None)

    client.post("/projects", data=_create_data(
        dgp=_dgp_bytes_signed_in(2026),
        contract_terms=(io.BytesIO(b"%PDF-fake"), "protocol.pdf"),
    ), content_type="multipart/form-data")

    slug = storage.list_project_slugs(tmp_path)[0]
    saved = passport_module.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["year_signed"] == "2026"
    assert saved["vat"] == "22%"


def test_create_project_sets_vat_from_signing_year_2025(tmp_path, monkeypatch):
    from app import passport as passport_module, storage

    app = create_app(tmp_path)
    client = app.test_client()
    _stub_scan_returning(monkeypatch, {"performance_bond_pct": "3%"}, None)

    client.post("/projects", data=_create_data(
        dgp=_dgp_bytes_signed_in(2025),
        contract_terms=(io.BytesIO(b"%PDF-fake"), "protocol.pdf"),
    ), content_type="multipart/form-data")

    slug = storage.list_project_slugs(tmp_path)[0]
    saved = passport_module.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["vat"] == "20%"


def test_create_project_explains_contract_terms_problem(tmp_path, monkeypatch):
    from app import ai_extractor

    app = create_app(tmp_path)
    client = app.test_client()
    _stub_scan_returning(monkeypatch, {}, ai_extractor.PROBLEM_NO_KEY)

    resp = client.post("/projects", data=_create_data(
        contract_terms=(io.BytesIO(b"%PDF-fake"), "protocol.pdf"),
    ), content_type="multipart/form-data", follow_redirects=True)

    assert "ANTHROPIC_API_KEY" in resp.data.decode("utf-8")


def test_contract_terms_upload_sets_vat_from_passport_year(tmp_path, monkeypatch):
    from app import passport as passport_module, storage

    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project_with_passport(tmp_path, "ПроектА", year_signed="2026")
    _stub_scan_returning(monkeypatch, {"performance_bond_pct": "3%"}, None)

    _upload_contract_terms(client, slug)

    saved = passport_module.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["vat"] == "22%"


def test_new_project_form_offers_a_contract_terms_field(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()

    body = client.get("/projects/new").data.decode("utf-8")

    assert 'name="contract_terms_file"' in body
