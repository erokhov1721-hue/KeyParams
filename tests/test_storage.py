import os

import pytest
from app import storage


def test_slugify_replaces_spaces():
    assert storage.slugify("Проспект Мира") == "Проспект_Мира"


def test_slugify_strips_invalid_chars():
    assert storage.slugify('One:Tower/2*?') == "OneTower2"


def test_slugify_empty_raises():
    with pytest.raises(ValueError):
        storage.slugify("   ")


def test_slugify_strips_trailing_dot():
    # Windows silently drops a trailing dot from a directory name, so keeping
    # it in the slug would make the stored slug diverge from the real folder.
    assert storage.slugify("ЖК Мира 2025 г.") == "ЖК_Мира_2025_г"


def test_slugify_rejects_reserved_device_name():
    with pytest.raises(ValueError):
        storage.slugify("COM1")


def test_unique_slug_returns_base_when_free(tmp_path):
    assert storage.unique_slug(tmp_path, "mira") == "mira"


def test_unique_slug_appends_number_when_taken(tmp_path):
    (tmp_path / "mira").mkdir()
    assert storage.unique_slug(tmp_path, "mira") == "mira_2"


def test_create_project_creates_raw_dir(tmp_path):
    slug = storage.create_project(tmp_path, "Проспект Мира")
    assert (tmp_path / slug / "raw").is_dir()


def test_create_project_avoids_collision(tmp_path):
    slug1 = storage.create_project(tmp_path, "Мира")
    slug2 = storage.create_project(tmp_path, "Мира")
    assert slug1 != slug2


def test_list_project_slugs_on_empty_root(tmp_path):
    empty_root = tmp_path / "does_not_exist_yet"
    assert storage.list_project_slugs(empty_root) == []


def _finish_project(root, slug):
    """Make a created project dir look complete by giving it a passport.json."""
    storage.passport_path(root, slug).write_text("{}", encoding="utf-8")


def test_list_project_slugs_returns_sorted_names(tmp_path):
    for name in ("Bravo", "Alpha"):
        _finish_project(tmp_path, storage.create_project(tmp_path, name))
    assert storage.list_project_slugs(tmp_path) == ["Alpha", "Bravo"]


def test_list_project_slugs_skips_dir_without_passport(tmp_path):
    """An orphaned project dir (no passport.json) must not be listed."""
    storage.create_project(tmp_path, "Orphan")
    _finish_project(tmp_path, storage.create_project(tmp_path, "Good"))
    assert storage.list_project_slugs(tmp_path) == ["Good"]


def test_delete_project_removes_directory(tmp_path):
    slug = storage.create_project(tmp_path, "Мира")
    _finish_project(tmp_path, slug)
    storage.delete_project(tmp_path, slug)
    assert not (tmp_path / slug).exists()


def test_delete_project_missing_slug_is_a_noop(tmp_path):
    storage.delete_project(tmp_path, "does-not-exist")


@pytest.mark.skipif(
    os.name != "nt", reason="only Windows refuses to delete a file another program holds open"
)
def test_delete_project_with_a_file_in_use_still_makes_it_disappear(tmp_path):
    """A locked upload must not keep a deleted project alive.

    Real case: the estimate was still open (Excel, an antivirus scan), so
    Windows refused to remove smeta.xlsx — and it refuses to rename the
    file or the folder around it too, so there's nowhere to move it aside
    to. What the user asked for still has to happen: the project goes now
    and never comes back, and the files left behind are swept up later.
    """
    slug = storage.create_project(tmp_path, "Смета открыта")
    _finish_project(tmp_path, slug)
    estimate = storage.estimate_path(tmp_path, slug)
    estimate.write_bytes(b"PK\x03\x04")

    with open(estimate, "rb"):
        storage.delete_project(tmp_path, slug)
        assert slug not in storage.list_project_slugs(tmp_path)


@pytest.mark.skipif(
    os.name != "nt", reason="only Windows refuses to delete a file another program holds open"
)
def test_purge_deleted_finishes_a_delete_once_the_file_is_free(tmp_path):
    slug = storage.create_project(tmp_path, "Смета открыта")
    _finish_project(tmp_path, slug)
    storage.estimate_path(tmp_path, slug).write_bytes(b"PK\x03\x04")

    with open(storage.estimate_path(tmp_path, slug), "rb"):
        storage.delete_project(tmp_path, slug)
        storage.purge_deleted(tmp_path)
        assert (tmp_path / slug).exists(), "cannot be gone while the file is still held open"

    storage.purge_deleted(tmp_path)

    assert not (tmp_path / slug).exists()


def test_purge_deleted_leaves_live_projects_alone(tmp_path):
    slug = storage.create_project(tmp_path, "Живой")
    _finish_project(tmp_path, slug)

    storage.purge_deleted(tmp_path)

    assert storage.list_project_slugs(tmp_path) == [slug]


def test_purge_deleted_leaves_a_half_created_project_alone(tmp_path):
    # A folder with no passport.json is either an upload still in progress
    # or the debris of a crashed creation. Neither was flagged for deletion,
    # so the sweep must not touch it — deleting one mid-upload would destroy
    # a project the user is in the middle of creating.
    slug = storage.create_project(tmp_path, "Ещё грузится")

    storage.purge_deleted(tmp_path)

    assert (tmp_path / slug).exists()


def test_raw_dir_and_passport_path(tmp_path):
    assert storage.raw_dir(tmp_path, "mira") == tmp_path / "mira" / "raw"
    assert storage.passport_path(tmp_path, "mira") == tmp_path / "mira" / "passport.json"
