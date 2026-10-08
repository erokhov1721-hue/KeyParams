"""A local log of corrections people make to contract terms the program found.

Each line of ``contract_corrections.jsonl`` (next to the projects folder, not
in it — on the server that is the /data volume) records one field a person
changed after recognition filled it: which protocol file (its SHA-256), the
field, what was found and by which method, what it was corrected to, and why
it had been flagged, if it had. Nothing leaves the machine; the log is what
new golden protocols are drawn from.

Only the first correction of a found value is recorded: after that the value
is the person's own, not the program's.
"""

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

FILE_NAME = "contract_corrections.jsonl"

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


def record(root: Path, entry: dict) -> None:
    """Append one correction as a line of JSON; the time is added here."""
    line = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    path = log_path(root)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def read_all(root: Path) -> list:
    """Every recorded correction, oldest first; a damaged line is skipped."""
    path = log_path(root)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries
