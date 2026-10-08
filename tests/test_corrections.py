"""Журнал исправлений найденных условий договора."""

from app import corrections, create_app, passport, storage


def _root(tmp_path):
    """Папка проектов внутри своей временной: журнал лежит уровнем выше неё,
    и у разных тестов он не должен быть общим."""
    return tmp_path / "projects"


def _project(tmp_path, protocol=b"%PDF-1.4 protocol"):
    slug = storage.create_project(tmp_path, "Объект")
    data = passport.build_passport("Объект")
    data.update({
        "smr_term": "38", "advance_payment": "0%", "bank_guarantee": "Не включено",
        "performance_bond_pct": "3%", "vat": "20%",
        "contract_auto_fields": ["smr_term", "advance_payment", "bank_guarantee"],
        "contract_sources": {"smr_term": "tesseract", "advance_payment": "tesseract"},
        "contract_review": {"advance_payment": [{"reason": "zero", "text": "0% — проверьте"}]},
    })
    passport.save_passport(data, storage.passport_path(tmp_path, slug))
    path = storage.contract_terms_path(tmp_path, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(protocol)
    return slug


def _edit(client, tmp_path, slug, **values):
    data = passport.load_passport(storage.passport_path(tmp_path, slug))
    form = {f: data.get(f) or "" for f in passport.CONTRACT_FIELDS}
    form.update(values)
    form["version"] = data["version"]
    return client.post(f"/projects/{slug}/contract", data=form)


def test_correcting_a_found_value_is_logged_with_its_file_and_method(tmp_path):
    tmp_path = _root(tmp_path)
    slug = _project(tmp_path)
    client = create_app(tmp_path).test_client()

    _edit(client, tmp_path, slug, smr_term="33", advance_payment="30%")

    entries = corrections.read_all(tmp_path)
    assert [(e["field"], e["found"], e["corrected"], e["method"]) for e in entries] == [
        ("smr_term", "38", "33", "tesseract"),
        ("advance_payment", "0%", "30%", "tesseract"),
    ]
    assert entries[1]["review"] == ["zero"]
    assert entries[0]["file_sha256"] == corrections.file_sha256(
        storage.contract_terms_path(tmp_path, slug),
    )
    assert entries[0]["project"] == slug and entries[0]["time"]


def test_a_value_typed_by_hand_or_left_as_is_is_not_logged(tmp_path):
    tmp_path = _root(tmp_path)
    slug = _project(tmp_path)
    client = create_app(tmp_path).test_client()

    # performance_bond_pct — не найденное программой; остальное не меняется.
    _edit(client, tmp_path, slug, performance_bond_pct="2,5%")

    assert corrections.read_all(tmp_path) == []


def test_only_the_first_correction_of_a_field_is_logged(tmp_path):
    tmp_path = _root(tmp_path)
    slug = _project(tmp_path)
    client = create_app(tmp_path).test_client()

    _edit(client, tmp_path, slug, smr_term="33")
    _edit(client, tmp_path, slug, smr_term="34")

    assert [e["corrected"] for e in corrections.read_all(tmp_path)] == ["33"]


def test_the_log_lives_outside_the_projects_folder(tmp_path):
    tmp_path = _root(tmp_path)
    assert corrections.log_path(tmp_path).parent == tmp_path.parent
    corrections.record(tmp_path, {"field": "smr_term"})

    assert storage.list_project_slugs(tmp_path) == []
    assert corrections.read_all(tmp_path)[0]["field"] == "smr_term"
