"""A local log of contract-terms recognitions and of corrections to them.

Each line of ``contract_recognition_log.jsonl`` (next to the projects folder,
not in it — on the server that is the /data volume, so it travels with the
data and its backups) is one event:

- ``"recognition"`` — a protocol was read: which file (its SHA-256), every
  field found with its value, method and reasons to check it, the fields not
  found, the problem and notes, the scan order and how long it took;
- ``"correction"`` — a person changed a value the program had found: the
  field, what was found and by which method, what it became, and why it had
  been flagged.

Together they give the accuracy of each method on real uploads; nothing
leaves the machine. Only the first correction of a found value is logged:
after that the value is the person's own, not the program's.
"""

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

FILE_NAME = "contract_recognition_log.jsonl"
# Where corrections went before recognitions were logged too; still read.
LEGACY_FILE_NAME = "contract_corrections.jsonl"

EVENT_RECOGNITION = "recognition"
EVENT_CORRECTION = "correction"

_lock = threading.Lock()


def log_path(root: Path) -> Path:
    return Path(root).parent / FILE_NAME


def file_sha256(path) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append(root: Path, entry: dict) -> None:
    line = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    path = log_path(root)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def record(root: Path, entry: dict) -> None:
    """Append one correction; the event type and the time are added here."""
    _append(root, {"event": EVENT_CORRECTION, **entry})


def record_recognition(root: Path, *, project, project_name, file_path, mode,
                       data, problem, scan_order, seconds) -> None:
    """Append one reading of a protocol.

    ``data`` is what ``passport.build_contract_terms`` returned (or ``{}`` if
    it never got to read the file); ``mode`` — "create" for a new project's
    protocol, "replace" for a protocol uploaded again.
    """
    sources = data.get("contract_sources") or {}
    review = data.get("contract_review") or {}
    fields, missing = {}, []
    for field in ("smr_term", "advance_payment", "bank_guarantee", "performance_bond_pct", "vat"):
        value = data.get(field)
        if value is None:
            missing.append(field)
            continue
        items = review.get(field) or []
        fields[field] = {
            "value": value,
            "method": sources.get(field),
            "review": [item["reason"] for item in items] if isinstance(items, list) else ["nonstandard"],
        }
    _append(root, {
        "event": EVENT_RECOGNITION,
        "project": project, "project_name": project_name,
        "file_sha256": file_sha256(file_path), "mode": mode,
        "fields": fields, "missing": missing,
        "problem": problem, "notes": data.get("contract_notes") or [],
        "scan_order": scan_order, "seconds": round(seconds, 1),
    })


def read_all(root: Path) -> list:
    """Every logged event, oldest first — corrections from the legacy file
    included; a damaged line is skipped."""
    entries = []
    for path in (Path(root).parent / LEGACY_FILE_NAME, log_path(root)):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry.setdefault("event", EVENT_CORRECTION)
            entries.append(entry)
    return entries
