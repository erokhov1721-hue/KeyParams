"""Сводка по журналу распознаваний: только цифры, без значений и названий."""

import json

from app import corrections, recognition_stats


def _recognition(fields, *, pages=2, seconds=10.0, problem=None, sha="a"):
    return {
        "event": "recognition", "project": "Секретный_объект",
        "project_name": "Секретный объект", "file_sha256": sha,
        "fields": fields, "problem": problem, "pages": pages, "seconds": seconds,
    }


def _found(method, *reasons, value="сорок семь"):
    return {"value": value, "method": method, "review": list(reasons)}


ENTRIES = [
    _recognition({
        "smr_term": _found("text"),
        "advance_payment": _found("tesseract", "zero", value="0%"),
        "vat": _found("rule"),
    }, pages=2, seconds=10.0, sha="a"),
    _recognition({
        "smr_term": _found("tesseract", "disagree", "reread"),
        "bank_guarantee": _found("tesseract", "nonstandard", value="Тайное условие"),
    }, pages=1, seconds=12.0, sha="b"),
    _recognition({}, pages=None, seconds=0.0, problem="busy", sha="b"),
    {"event": "correction", "field": "advance_payment", "found": "пусто-пусто",
     "corrected": "тридцать процентов", "method": "tesseract", "project_name": "Секретный объект"},
]


def test_counts_protocols_but_not_the_ones_a_busy_server_never_read():
    p = recognition_stats.summarize(ENTRIES)["protocols"]

    assert p == {
        "recognitions": 3, "read": 2, "not_read_busy": 1,
        "distinct_files": 2, "problems": {},
    }


def test_share_of_fields_by_method_out_of_every_field_of_every_protocol():
    s = recognition_stats.summarize(ENTRIES)

    assert s["field_slots"] == 10
    assert s["count_by_method"] == {"не найдено": 5, "tesseract": 3, "text": 1, "rule": 1}
    assert s["share_by_method"]["tesseract"] == 0.3
    assert s["by_field"]["smr_term"] == {
        "found": 2, "found_share": 1.0, "methods": {"text": 1, "tesseract": 1},
    }


def test_review_flags_are_counted_by_reason():
    r = recognition_stats.summarize(ENTRIES)["review"]

    assert r["flagged_fields"] == 3
    assert r["by_reason"] == {"zero": 1, "disagree": 1, "reread": 1, "nonstandard": 1}


def test_corrections_by_field_and_as_a_share_of_what_was_found():
    c = recognition_stats.summarize(ENTRIES)["corrections"]

    assert c["by_field"] == {"advance_payment": 1}
    assert c["by_method"] == {"tesseract": 1}
    assert c["share_of_found"]["advance_payment"] == 1.0


def test_time_per_page():
    t = recognition_stats.summarize(ENTRIES)["time"]

    # 22 с на 3 страницы; по протоколам — 5 и 12 с на страницу.
    assert t["pages"] == 3
    assert t["seconds_per_page_overall"] == 7.3
    assert t["seconds_per_page_median"] == 8.5
    assert t["seconds_per_page_max"] == 12.0


def test_the_report_holds_no_values_and_no_object_names():
    summary = recognition_stats.summarize(ENTRIES)
    text = recognition_stats.format_report(summary) + json.dumps(summary, ensure_ascii=False)

    for secret in ("Секретный", "Тайное условие", "сорок семь", "пусто-пусто", "тридцать"):
        assert secret not in text
    assert "Tesseract" in text and "способы разошлись" in text


def test_an_empty_log_gives_a_report_too():
    summary = recognition_stats.summarize([])

    assert summary["protocols"]["read"] == 0
    assert "нет записей" in recognition_stats.format_report(summary)


def test_reads_the_log_from_the_projects_folder(tmp_path, capsys):
    root = tmp_path / "projects"
    corrections.record(root, {"field": "vat", "method": "text"})

    assert recognition_stats.main([str(root), "--json"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["corrections"]["by_field"] == {"vat": 1}


def test_reads_a_log_file_given_directly(tmp_path, capsys):
    path = tmp_path / "copy.jsonl"
    path.write_text(json.dumps(ENTRIES[0], ensure_ascii=False) + "\n", encoding="utf-8")

    recognition_stats.main([str(path)])

    assert "прочитано: 1" in capsys.readouterr().out
