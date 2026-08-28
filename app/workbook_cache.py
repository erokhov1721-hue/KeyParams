"""A small per-path cache of already-parsed estimate workbooks.

One project page view reads the same estimate file several times over —
concrete volume, facade area, section costs and the sheet render each open
it independently (``app.estimate_sections`` and ``app.estimate``). Caching
the parsed ``Workbook`` here lets a second read of the same file reuse it
instead of re-opening and re-parsing the same bytes from disk.

Keyed on (path, data_only, mtime, size) rather than path alone: a re-upload
that replaces the file at the same path changes its mtime/size, so the old
parse simply misses and gets replaced — it never needs to be told to expire.

Only ever holds workbooks loaded in the default (non-``read_only``) mode.
A ``read_only`` workbook keeps its underlying zip archive open for as long
as the object lives; caching one here would leave that file handle open
past the end of the request, which on Windows blocks a later re-upload from
replacing the same file.
"""

import threading
from collections import OrderedDict
from pathlib import Path

import openpyxl

MAX_ENTRIES = 8

_lock = threading.Lock()
_cache = OrderedDict()


def _key(path, data_only):
    resolved = Path(path).resolve()
    stat = resolved.stat()
    return (str(resolved), bool(data_only), stat.st_mtime_ns, stat.st_size)


def get(path, data_only):
    """The already-parsed workbook for ``(path, data_only)``, or None if it
    isn't cached, or the file has changed since (a re-upload)."""
    try:
        key = _key(path, data_only)
    except OSError:
        return None
    with _lock:
        wb = _cache.get(key)
        if wb is not None:
            _cache.move_to_end(key)
        return wb


def put(path, data_only, workbook):
    try:
        key = _key(path, data_only)
    except OSError:
        return
    with _lock:
        _cache[key] = workbook
        _cache.move_to_end(key)
        while len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)


def get_or_load(path, data_only):
    """``get``, loading and caching a fresh copy via openpyxl on a miss.

    For a caller that needs the file opened some other way (a BytesIO
    buffer, say, to avoid leaving a locked file handle behind if parsing
    fails partway) — load it that way and call ``get``/``put`` directly
    instead of this.
    """
    wb = get(path, data_only)
    if wb is not None:
        return wb
    wb = openpyxl.load_workbook(path, data_only=data_only)
    put(path, data_only, wb)
    return wb


def invalidate(path):
    """Drop every cached entry for this path (both ``data_only`` variants).

    (path, mtime, size) alone is not quite enough to rule out ever serving a
    re-upload's predecessor: two uploads landing within the filesystem's
    timestamp resolution, or two estimates that just happen to be the same
    byte size, would otherwise key identically despite different content.
    A caller that replaces a cached file should call this right after —
    ``app.routes.upload_estimate`` does, once the new file has taken the old
    one's place — so the next read is never in doubt.
    """
    resolved = str(Path(path).resolve())
    with _lock:
        for key in [k for k in _cache if k[0] == resolved]:
            del _cache[key]


def clear():
    """Test-only: drop every cached workbook."""
    with _lock:
        _cache.clear()
