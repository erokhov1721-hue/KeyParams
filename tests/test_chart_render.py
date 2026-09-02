import json

from app import chart_render


def _row(label, peer_pct, own_pct, deviation_pct=None):
    return {
        "label": label,
        "peer_pct": peer_pct,
        "own_pct": own_pct,
        "deviation_pct": deviation_pct,
    }


def test_class_average_chart_data_passes_through_the_series():
    rows = [
        _row("Фасадные работы", 66.7, 100.0, 50.0),
        _row("Кровля", 100.0, 80.0, -20.0),
    ]

    data = chart_render.class_average_chart_data(rows, "Проспект мира")

    assert data["labels"] == ["Фасадные работы", "Кровля"]
    assert data["peer_pct"] == [66.7, 100.0]
    assert data["own_pct"] == [100.0, 80.0]
    assert data["deviation_pct"] == [50.0, -20.0]
    assert data["own_name"] == "Проспект мира"
    assert data["has_deviation"] is True


def test_class_average_chart_data_is_json_serialisable():
    # The template hands this straight to |tojson — a value that survives a
    # round trip through json.dumps/json.loads is the real requirement, not
    # just "looks like a dict".
    rows = [_row("Кровля", 100.0, 80.0, None)]

    data = chart_render.class_average_chart_data(rows, "Б")
    round_tripped = json.loads(json.dumps(data))

    assert round_tripped == data


def test_class_average_chart_data_keeps_a_missing_deviation_as_none():
    # None must reach the client as JSON null, not NaN (invalid JSON) or 0
    # (a real deviation figure) — spanGaps: false on the client relies on
    # null to know where to break the line.
    rows = [
        _row("Фасадные работы", 66.7, 100.0, 50.0),
        _row("Кровля", 100.0, 80.0, None),
    ]

    data = chart_render.class_average_chart_data(rows, "Проспект мира")

    assert data["deviation_pct"] == [50.0, None]
    assert data["has_deviation"] is True


def test_class_average_chart_data_has_deviation_false_when_every_row_lacks_one():
    # Mirrors render_class_average_chart's own any(...) check: with nothing
    # to plot, the client should skip the line dataset rather than draw an
    # empty one.
    rows = [
        _row("Фасадные работы", 66.7, 100.0, None),
        _row("Кровля", 100.0, 80.0, None),
    ]

    data = chart_render.class_average_chart_data(rows, "Проспект мира")

    assert data["has_deviation"] is False


def test_class_average_chart_data_shortens_long_labels_like_the_png_chart_did():
    long_label = "Подготовительные работы и содержание площадки (включая аренду)"
    rows = [_row(long_label, 50.0, 60.0)]

    data = chart_render.class_average_chart_data(rows, "Проспект мира")

    assert data["labels"] == [chart_render._short_label(long_label)]
    assert "(" not in data["labels"][0]
