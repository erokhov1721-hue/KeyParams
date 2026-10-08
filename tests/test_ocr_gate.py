"""Сколько сканов распознаётся одновременно и что видит тот, кому не хватило
места."""

import threading

import pytest

from app import create_app, passport, storage


def _hold_slot(started, release):
    with passport._ocr_slot():
        started.set()
        release.wait(5)


def test_a_scan_beyond_the_slots_and_the_queue_is_turned_away(monkeypatch):
    monkeypatch.setenv(passport.OCR_SLOTS_ENV, "1")
    monkeypatch.setenv(passport.OCR_QUEUE_ENV, "0")
    started, release = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_slot, args=(started, release))
    holder.start()
    started.wait(5)
    try:
        with pytest.raises(passport.RecognitionBusy):
            with passport._ocr_slot():
                pass
    finally:
        release.set()
        holder.join(5)


def test_a_scan_in_the_queue_waits_for_a_free_slot(monkeypatch):
    monkeypatch.setenv(passport.OCR_SLOTS_ENV, "1")
    monkeypatch.setenv(passport.OCR_QUEUE_ENV, "1")
    started, release = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_slot, args=(started, release))
    holder.start()
    started.wait(5)
    threading.Timer(0.2, release.set).start()

    with passport._ocr_slot():
        got_in = True

    holder.join(5)
    assert got_in


def test_a_scan_that_waits_too_long_is_turned_away(monkeypatch):
    monkeypatch.setenv(passport.OCR_SLOTS_ENV, "1")
    monkeypatch.setenv(passport.OCR_QUEUE_ENV, "1")
    monkeypatch.setattr(passport, "OCR_WAIT_SECONDS", 0.2)
    started, release = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_slot, args=(started, release))
    holder.start()
    started.wait(5)
    try:
        with pytest.raises(passport.RecognitionBusy):
            with passport._ocr_slot():
                pass
    finally:
        release.set()
        holder.join(5)


def test_slots_are_given_back_after_a_failure():
    with pytest.raises(ValueError):
        with passport._ocr_slot():
            raise ValueError("распознавание упало")

    assert passport._ocr_running == 0


def test_a_busy_server_keeps_the_old_protocol_and_says_why(tmp_path, monkeypatch):
    slug = storage.create_project(tmp_path, "Объект")
    data = passport.build_passport("Объект")
    data.update({"smr_term": "33", "contract_auto_fields": ["smr_term"]})
    passport.save_passport(data, storage.passport_path(tmp_path, slug))
    old = storage.contract_terms_path(tmp_path, slug)
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"%PDF-1.4 old")

    def busy(*args, **kwargs):
        raise passport.RecognitionBusy()

    monkeypatch.setattr(passport, "build_contract_terms", busy)
    client = create_app(tmp_path).test_client()
    import io
    resp = client.post(
        f"/projects/{slug}/contract-terms",
        data={"contract_terms_file": (io.BytesIO(b"%PDF-1.4 new"), "p.pdf"),
              "version": passport.load_passport(storage.passport_path(tmp_path, slug))["version"]},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert "problem=busy" in resp.headers["Location"]
    assert old.read_bytes() == b"%PDF-1.4 old"
    assert passport.load_passport(storage.passport_path(tmp_path, slug))["smr_term"] == "33"
    page = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "распознаёт другие протоколы" in page
