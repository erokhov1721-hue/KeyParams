import pytest
from app import storage


def test_slugify_replaces_spaces():
    assert storage.slugify("Проспект Мира") == "Проспект_Мира"


def test_slugify_strips_invalid_chars():
    assert storage.slugify('One:Tower/2*?') == "OneTower2"


def test_slugify_empty_raises():
    with pytest.raises(ValueError):
        storage.slugify("   ")


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


def test_list_project_slugs_returns_sorted_names(tmp_path):
    storage.create_project(tmp_path, "Bravo")
    storage.create_project(tmp_path, "Alpha")
    assert storage.list_project_slugs(tmp_path) == ["Alpha", "Bravo"]


def test_raw_dir_and_passport_path(tmp_path):
    assert storage.raw_dir(tmp_path, "mira") == tmp_path / "mira" / "raw"
    assert storage.passport_path(tmp_path, "mira") == tmp_path / "mira" / "passport.json"
