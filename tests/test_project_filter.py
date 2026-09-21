from app import project_filter


def test_value_reads_completed_as_yes_or_no():
    assert project_filter._value({"completed": True}, "completed") == "yes"
    assert project_filter._value({"completed": False}, "completed") == "no"
    assert project_filter._value({}, "completed") == "no"


def test_display_label_maps_completed_values_to_russian_labels():
    assert project_filter.display_label("completed", "yes") == "Завершён"
    assert project_filter.display_label("completed", "no") == "В работе"


def test_display_label_falls_back_to_the_value_for_other_groups():
    assert project_filter.display_label("contractor", "АНТТЕК") == "АНТТЕК"
    assert project_filter.display_label("contractor", project_filter.NOT_SET) == project_filter.NOT_SET_LABEL


def test_build_filters_projects_by_completed_status():
    passports = {
        "a": {"completed": True},
        "b": {"completed": False},
    }
    result = project_filter.build(passports, _Args({"completed": ["yes"]}))

    assert result["slugs"] == ["a"]
    completed_group = next(g for g in result["groups"] if g["key"] == "completed")
    options_by_value = {o["value"]: o for o in completed_group["options"]}
    assert options_by_value["yes"]["label"] == "Завершён"
    assert options_by_value["yes"]["count"] == 1
    assert options_by_value["no"]["label"] == "В работе"
    assert options_by_value["no"]["count"] == 1


class _Args:
    """Минимальная замена werkzeug MultiDict для build()/``getlist``."""

    def __init__(self, data):
        self._data = data

    def getlist(self, key):
        return self._data.get(key, [])
