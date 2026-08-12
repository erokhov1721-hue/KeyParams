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


def test_delete_project_unknown_slug_404s(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    resp = client.post("/projects/does-not-exist/delete")
    assert resp.status_code == 404


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
