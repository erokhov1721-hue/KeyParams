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


# --- журнал распознаваний ---

def _stub_scan(monkeypatch, fields):
    monkeypatch.setattr(passport.pdf_reader, "read_pdf_text", lambda path: "")
    monkeypatch.setattr(passport.pdf_reader, "render_pages_to_images", lambda path, **kw: [b"png"])
    monkeypatch.setattr(
        passport.ai_extractor, "extract_contract_terms_from_images",
        lambda images, project_name=None: (fields, None),
    )
    monkeypatch.setenv(passport.SCAN_ORDER_ENV, "claude")


def _upload(client, tmp_path, slug, content=b"%PDF-1.4 scan"):
    import io
    version = passport.load_passport(storage.passport_path(tmp_path, slug))["version"]
    return client.post(
        f"/projects/{slug}/contract-terms",
        data={"contract_terms_file": (io.BytesIO(content), "p.pdf"), "version": version},
        content_type="multipart/form-data",
    )


def test_every_recognition_is_logged_with_its_fields_methods_and_file(tmp_path, monkeypatch):
    import hashlib
    tmp_path = _root(tmp_path)
    slug = _project(tmp_path)
    client = create_app(tmp_path).test_client()
    _stub_scan(monkeypatch, {"smr_term": "33", "advance_payment": "0%"})

    _upload(client, tmp_path, slug)

    (entry,) = [e for e in corrections.read_all(tmp_path) if e["event"] == "recognition"]
    assert entry["mode"] == "replace" and entry["project"] == slug
    assert entry["file_sha256"] == hashlib.sha256(b"%PDF-1.4 scan").hexdigest()
    assert entry["fields"]["smr_term"] == {"value": "33", "method": "claude", "review": []}
    assert entry["fields"]["advance_payment"]["review"] == ["zero"]
    assert "bank_guarantee" in entry["missing"]
    assert entry["scan_order"] == ["claude"]
    assert entry["seconds"] >= 0


def test_a_busy_server_is_logged_too(tmp_path, monkeypatch):
    tmp_path = _root(tmp_path)
    slug = _project(tmp_path)
    client = create_app(tmp_path).test_client()

    def busy(*args, **kwargs):
        raise passport.RecognitionBusy()

    monkeypatch.setattr(passport, "build_contract_terms", busy)

    _upload(client, tmp_path, slug)

    (entry,) = corrections.read_all(tmp_path)
    assert entry["event"] == "recognition"
    assert entry["problem"] == passport.CONTRACT_PROBLEM_BUSY
    assert entry["fields"] == {}


def test_a_new_projects_protocol_is_logged_as_create(tmp_path, monkeypatch):
    import io

    from tests.test_routes import _create_data

    tmp_path = _root(tmp_path)
    client = create_app(tmp_path).test_client()
    _stub_scan(monkeypatch, {"smr_term": "30"})

    resp = client.post("/projects", data=_create_data(
        contract_terms=(io.BytesIO(b"%PDF-fake"), "protocol.pdf"),
    ), content_type="multipart/form-data")

    assert resp.status_code == 302
    (entry,) = [e for e in corrections.read_all(tmp_path) if e["event"] == "recognition"]
    assert entry["mode"] == "create"
    assert entry["project"] == storage.list_project_slugs(tmp_path)[0]
    assert entry["fields"]["smr_term"]["value"] == "30"


def test_corrections_from_the_old_file_are_still_read(tmp_path):
    tmp_path = _root(tmp_path)
    old = tmp_path.parent / corrections.LEGACY_FILE_NAME
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text('{"field": "smr_term", "found": "38", "corrected": "33"}\n', encoding="utf-8")
    corrections.record(tmp_path, {"field": "vat"})

    entries = corrections.read_all(tmp_path)

    assert [(e["event"], e["field"]) for e in entries] == [
        ("correction", "smr_term"), ("correction", "vat"),
    ]


def test_a_recognition_records_how_many_pages_the_protocol_has(tmp_path, monkeypatch):
    import io

    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    for _ in range(3):
        pdf.drawString(100, 700, "page")
        pdf.showPage()
    pdf.save()
    path = tmp_path / "protocol.pdf"
    path.write_bytes(buf.getvalue())
    root = _root(tmp_path)

    corrections.record_recognition(
        root, project="p", project_name="P", file_path=path, mode="create",
        data={}, problem=None, scan_order=[], seconds=1.0,
    )

    (entry,) = corrections.read_all(root)
    assert entry["pages"] == 3
