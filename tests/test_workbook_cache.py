import os

from openpyxl import Workbook

from app import workbook_cache


def _save(tmp_path, name="book.xlsx"):
    path = tmp_path / name
    Workbook().save(path)
    return path


def test_get_is_none_before_anything_is_cached(tmp_path):
    workbook_cache.clear()
    path = _save(tmp_path)
    assert workbook_cache.get(path, data_only=True) is None


def test_get_or_load_returns_the_same_object_on_a_second_call(tmp_path):
    workbook_cache.clear()
    path = _save(tmp_path)
    first = workbook_cache.get_or_load(path, data_only=True)
    second = workbook_cache.get_or_load(path, data_only=True)
    assert first is second


def test_get_or_load_keeps_data_only_variants_separate(tmp_path):
    workbook_cache.clear()
    path = _save(tmp_path)
    values = workbook_cache.get_or_load(path, data_only=True)
    formulas = workbook_cache.get_or_load(path, data_only=False)
    assert values is not formulas


def test_a_changed_file_is_not_served_from_the_stale_cache(tmp_path):
    # A re-upload replaces the file at the same path — the cache must key on
    # more than the path, or the page would keep showing the old estimate
    # forever after a replace.
    workbook_cache.clear()
    path = _save(tmp_path)
    first = workbook_cache.get_or_load(path, data_only=True)

    wb = Workbook()
    wb.active["A1"] = "changed"
    wb.save(path)
    # Nudge the mtime forward in case the filesystem's clock resolution is
    # coarser than the time this test takes to reach here.
    changed = os.path.getmtime(path) + 5
    os.utime(path, (changed, changed))

    second = workbook_cache.get_or_load(path, data_only=True)
    assert second is not first


def test_invalidate_forces_a_fresh_load_on_the_next_read(tmp_path):
    # (path, mtime, size) alone can coincide between two uploads (same
    # timestamp resolution, same byte size, different content) — the
    # explicit call is what a replace actually relies on, not the guess.
    workbook_cache.clear()
    path = _save(tmp_path)
    first = workbook_cache.get_or_load(path, data_only=True)

    workbook_cache.invalidate(path)

    second = workbook_cache.get_or_load(path, data_only=True)
    assert second is not first


def test_invalidate_drops_both_data_only_variants(tmp_path):
    workbook_cache.clear()
    path = _save(tmp_path)
    workbook_cache.get_or_load(path, data_only=True)
    workbook_cache.get_or_load(path, data_only=False)

    workbook_cache.invalidate(path)

    assert workbook_cache.get(path, data_only=True) is None
    assert workbook_cache.get(path, data_only=False) is None


def test_cache_evicts_the_oldest_entry_past_its_capacity(tmp_path):
    workbook_cache.clear()
    paths = [_save(tmp_path, name=f"book{i}.xlsx") for i in range(workbook_cache.MAX_ENTRIES + 2)]

    for path in paths:
        workbook_cache.get_or_load(path, data_only=True)

    assert workbook_cache.get(paths[0], data_only=True) is None
    assert workbook_cache.get(paths[-1], data_only=True) is not None
