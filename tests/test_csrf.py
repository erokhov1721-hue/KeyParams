import re

from app import create_app, passport as passport_module, storage


def _make_project(root, name="Проект"):
    slug = storage.create_project(root, name)
    data = {
        "project_name": name, "year_signed": None, "building_class": None,
        "general_contractor": None, "underground_area_sqm": None,
        "aboveground_area_sqm": None, "total_area_sqm": None, "ocr_fields": [],
    }
    passport_module.save_passport(data, storage.passport_path(root, slug))
    return slug


def _extract_token(html):
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "форма на странице не несёт поля csrf_token"
    return match.group(1)


def test_tests_run_with_csrf_checking_off_by_default(tmp_path):
    # The rest of the test suite posts to mutating routes without a token —
    # this is the setting that makes that keep working, and it is worth
    # pinning down explicitly rather than relying on it silently.
    app = create_app(tmp_path)

    assert app.config["WTF_CSRF_ENABLED"] is False


def test_a_post_without_a_csrf_token_is_rejected(tmp_path):
    app = create_app(tmp_path)
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    slug = _make_project(tmp_path)

    resp = client.post(f"/projects/{slug}/rename", data={"project_name": "Подмена"})

    assert resp.status_code == 400
    saved = passport_module.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["project_name"] == "Проект"


def test_a_post_with_a_valid_csrf_token_is_accepted(tmp_path):
    app = create_app(tmp_path)
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    slug = _make_project(tmp_path)

    page = client.get("/").get_data(as_text=True)
    token = _extract_token(page)

    resp = client.post(f"/projects/{slug}/rename", data={
        "project_name": "Новое имя", "csrf_token": token,
    })

    assert resp.status_code == 302
    saved = passport_module.load_passport(storage.passport_path(tmp_path, slug))
    assert saved["project_name"] == "Новое имя"


def test_every_mutating_form_on_the_project_page_carries_a_token(tmp_path):
    app = create_app(tmp_path)
    client = app.test_client()
    slug = _make_project(tmp_path)

    html = client.get(f"/projects/{slug}").get_data(as_text=True)

    form_count = html.count('method="post"')
    token_count = html.count('name="csrf_token"')
    assert form_count > 0
    assert token_count == form_count
