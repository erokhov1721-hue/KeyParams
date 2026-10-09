"""Сводка по журналу распознаваний протоколов (``app/corrections.py``).

Только сводные цифры — ни значений полей, ни названий объектов, ни имён
файлов: сколько протоколов прочитано, какую долю полей нашёл каждый способ,
сколько пометок «проверьте» и почему, сколько найденного исправили люди и
сколько времени уходит на страницу.

    python -m app.recognition_stats [папка проектов | файл журнала] [--json]

Без аргумента берётся папка проектов программы (``KEYPARAMS_PROJECTS_ROOT``),
как её находит сама программа. На сервере:

    docker exec keyparams python -m app.recognition_stats
"""

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

from . import corrections, passport

# Прочитать протокол не пытались — сервер был занят: в долях и во времени
# такие записи только исказили бы картину, они считаются отдельно.
_NOT_READ = {passport.CONTRACT_PROBLEM_BUSY, passport.CONTRACT_PROBLEM_BUSY_NEW}

REASON_LABELS = {
    passport.REVIEW_NONSTANDARD: "нестандартное условие",
    passport.REVIEW_ZERO: "ноль — не потерялась ли цифра",
    passport.REVIEW_DISAGREE: "способы разошлись",
    passport.REVIEW_REREAD: "прочитано повторно по ячейке",
}

PROBLEM_LABELS = {
    passport.CONTRACT_PROBLEM_NOTHING_FOUND: "ничего не найдено",
    passport.CONTRACT_PROBLEM_COLUMN_UNKNOWN: "не найден столбец объекта",
    passport.CONTRACT_PROBLEM_UNREADABLE: "файл не читается",
}

NOT_FOUND = "не найдено"


def summarize(entries) -> dict:
    """Сводные цифры по записям журнала (``corrections.read_all``)."""
    fields = passport.CONTRACT_FIELDS
    recognitions = [e for e in entries if e.get("event") == corrections.EVENT_RECOGNITION]
    read = [e for e in recognitions if e.get("problem") not in _NOT_READ]
    fixes = [e for e in entries if e.get("event") == corrections.EVENT_CORRECTION]

    by_method = Counter()
    by_field = {field: Counter() for field in fields}
    reasons = Counter()
    flagged_fields = 0
    for entry in read:
        found = entry.get("fields") or {}
        for field in fields:
            item = found.get(field)
            method = (item.get("method") or "?") if item else NOT_FOUND
            by_method[method] += 1
            by_field[field][method] += 1
            if item and item.get("review"):
                flagged_fields += 1
                reasons.update(item["review"])

    slots = len(read) * len(fields)
    found_count = Counter()
    for entry in read:
        for field in (entry.get("fields") or {}):
            found_count[field] += 1
    corrected = Counter(e.get("field") for e in fixes)
    corrected_by_method = Counter(e.get("method") or "?" for e in fixes)

    timed = [e for e in read if e.get("pages") and e.get("seconds") is not None]
    per_page = [e["seconds"] / e["pages"] for e in timed]
    total_pages = sum(e["pages"] for e in timed)

    return {
        "protocols": {
            "recognitions": len(recognitions),
            "read": len(read),
            "not_read_busy": len(recognitions) - len(read),
            "distinct_files": len({e.get("file_sha256") for e in read if e.get("file_sha256")}),
            "problems": dict(Counter(e["problem"] for e in read if e.get("problem"))),
        },
        "field_slots": slots,
        "share_by_method": {m: _share(n, slots) for m, n in by_method.most_common()},
        "count_by_method": dict(by_method.most_common()),
        "by_field": {
            field: {
                "found": found_count[field],
                "found_share": _share(found_count[field], len(read)),
                "methods": dict(by_field[field].most_common()),
            }
            for field in fields
        },
        "review": {
            "flagged_fields": flagged_fields,
            "flags": sum(reasons.values()),
            "by_reason": dict(reasons.most_common()),
        },
        "corrections": {
            "total": len(fixes),
            "by_field": {field: corrected[field] for field in fields if corrected[field]},
            "by_method": dict(corrected_by_method.most_common()),
            "share_of_found": {
                field: _share(corrected[field], found_count[field])
                for field in fields if found_count[field]
            },
        },
        "time": {
            "protocols_timed": len(timed),
            "pages": total_pages,
            "seconds_per_page_overall": _round(sum(e["seconds"] for e in timed) / total_pages) if total_pages else None,
            "seconds_per_page_median": _round(statistics.median(per_page)) if per_page else None,
            "seconds_per_page_max": _round(max(per_page)) if per_page else None,
        },
    }


def _share(part, whole):
    return round(part / whole, 3) if whole else None


def _round(value):
    return round(value, 1)


def _pct(share):
    return "—" if share is None else f"{share * 100:.0f}%"


def _method_label(method):
    if method == NOT_FOUND:
        return method
    return passport.METHOD_LABELS.get(method, method)


def format_report(summary) -> str:
    p = summary["protocols"]
    lines = [
        "Протоколы",
        f"  распознаваний в журнале: {p['recognitions']}",
        f"  прочитано: {p['read']} (разных файлов: {p['distinct_files']})",
        f"  не читались — сервер был занят: {p['not_read_busy']}",
    ]
    for problem, n in p["problems"].items():
        lines.append(f"  с проблемой «{PROBLEM_LABELS.get(problem, problem)}»: {n}")

    lines += ["", f"Доля полей по способу (всего полей: {summary['field_slots']})"]
    for method, share in summary["share_by_method"].items():
        n = summary["count_by_method"][method]
        lines.append(f"  {_method_label(method):<22} {n:>5}  {_pct(share):>5}")

    lines += ["", "По полям: найдено / чем"]
    for field, row in summary["by_field"].items():
        methods = ", ".join(
            f"{_method_label(m)} {n}" for m, n in row["methods"].items()
        )
        lines.append(
            f"  {passport.CONTRACT_FIELD_LABELS[field]:<22} {row['found']:>5}  "
            f"{_pct(row['found_share']):>5}  ({methods})"
        )

    r = summary["review"]
    lines += [
        "",
        f"Пометки «проверьте»: {r['flags']} (полей с пометкой: {r['flagged_fields']})",
    ]
    for reason, n in r["by_reason"].items():
        lines.append(f"  {REASON_LABELS.get(reason, reason):<32} {n:>5}")

    c = summary["corrections"]
    lines += ["", f"Исправления людьми: {c['total']}"]
    for field, n in c["by_field"].items():
        share = c["share_of_found"].get(field)
        lines.append(
            f"  {passport.CONTRACT_FIELD_LABELS[field]:<22} {n:>5}  "
            f"({_pct(share)} найденного)"
        )
    if c["by_method"]:
        lines.append("  по способу, которым было найдено: " + ", ".join(
            f"{_method_label(m)} {n}" for m, n in c["by_method"].items()
        ))

    t = summary["time"]
    lines += ["", "Время"]
    if t["pages"]:
        lines += [
            f"  протоколов с известным числом страниц: {t['protocols_timed']}, страниц: {t['pages']}",
            f"  в среднем на страницу: {t['seconds_per_page_overall']} с",
            f"  медиана по протоколам: {t['seconds_per_page_median']} с, наибольшее: {t['seconds_per_page_max']} с",
        ]
    else:
        lines.append("  нет записей с числом страниц (оно пишется в журнал с октября 2026)")
    return "\n".join(lines)


def _entries(target: Path):
    if target.is_file():
        return _read_file(target)
    return corrections.read_all(target)


def _read_file(path: Path):
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        entry.setdefault("event", corrections.EVENT_CORRECTION)
        entries.append(entry)
    return entries


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Сводка по журналу распознаваний протоколов.")
    parser.add_argument("target", nargs="?", help="папка проектов или файл журнала")
    parser.add_argument("--json", action="store_true", help="вывести цифры в JSON")
    args = parser.parse_args(argv)

    if args.target:
        target = Path(args.target)
    else:
        from . import _default_projects_root
        target = Path(os.environ.get("KEYPARAMS_PROJECTS_ROOT") or _default_projects_root())
    summary = summarize(_entries(target))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_report(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
