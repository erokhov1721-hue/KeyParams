"""The class-average comparison, drawn as a PNG instead of CSS bars.

Matplotlib runs headless here (``Agg``) — there is no display in a Flask
worker process, and the default backend would otherwise try to open one and
fail. The figure is rendered once per page view and handed to the template
as a data URI, so the browser needs no extra request and the image can't go
stale against the tables above it: both come from the same ``chart`` rows.
"""

from base64 import b64encode
from io import BytesIO

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (backend must be set first)

# Muted, theme-neutral palette: the page itself switches between a dark and
# a light theme from client-side JS alone (see base.html), which a
# server-rendered image can't follow. Bright saturated colours read fine on
# one background and disappear on the other; these mid-tones and a
# transparent figure background hold up on both instead of matching either.
PEER_COLOR = "#8fa39f"
OWN_COLOR = "#1c9a80"
DEVIATION_COLOR = "#c9862f"
GRID_COLOR = "#8a9c99"
TEXT_COLOR = "#7f9491"

# Inches per category, but capped: unbounded growth is what forced a
# horizontal scrollbar on a comparison with fifteen-plus work types. Past
# the cap, categories simply pack tighter — narrower bars read better than
# a chart wider than the page.
WIDTH_PER_CATEGORY = 0.62
MIN_WIDTH = 7.5
MAX_WIDTH = 10.5
HEIGHT = 6.0
DPI = 150

# A section label can run to a whole sentence in parentheses ("Подготовительные
# работы и содержание площадки (включая содержание прилегающей территории,
# аренда оборудования и т.п."). The chart only needs enough of it to name the
# category — the full text is already in the table above — so a trailing
# parenthetical is dropped outright rather than sliced mid-sentence, and
# anything still too long is cut at a word boundary instead of mid-word.
LABEL_MAX_CHARS = 24
LABEL_ROTATION = 55
# Single-letter prepositions/conjunctions ("и", "в", "с", "к", "у", "о", "а")
# left dangling at the end of a word-boundary cut read as an unfinished
# sentence rather than a shortened label — dropped along with the word before
# them would be if it didn't fit.
_DANGLING_WORDS = {"и", "в", "с", "к", "у", "о", "а", "на", "по", "от", "за", "до"}


def _short_label(label):
    """The label as it goes on the chart's own x-axis — not what's shown
    anywhere else, which keeps the full name in the table exact."""
    head = label.split(" (", 1)[0].rstrip()
    if len(head) <= LABEL_MAX_CHARS:
        return head
    cut = head[:LABEL_MAX_CHARS]
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]
    words = cut.split(" ")
    while len(words) > 1 and words[-1].lower().strip(",.;") in _DANGLING_WORDS:
        words.pop()
    return " ".join(words).rstrip(" ,;")


def render_class_average_chart(chart_rows, own_name):
    """The peer-average/own-value bars plus a deviation line on its own
    axis, as PNG bytes.

    ``chart_rows`` is ``comparison.build_class_average_comparison``'s own
    ``result["chart"]`` — same rows the tables above already show, so the
    picture can't disagree with them. Work-type labels go on a diagonal:
    with a dozen-plus categories, horizontal labels would either overlap or
    force the chart itself to stay narrow to fit them.
    """
    labels = [_short_label(row["label"]) for row in chart_rows]
    peer_pct = [row["peer_pct"] for row in chart_rows]
    own_pct = [row["own_pct"] for row in chart_rows]
    deviations = [row.get("deviation_pct") for row in chart_rows]

    count = len(chart_rows)
    width = min(MAX_WIDTH, max(MIN_WIDTH, count * WIDTH_PER_CATEGORY))
    fig, ax = plt.subplots(figsize=(width, HEIGHT), dpi=DPI)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    positions = range(count)
    bar_width = 0.36
    ax.bar(
        [i - bar_width / 2 for i in positions], peer_pct, bar_width,
        label="Средняя по классу", color=PEER_COLOR,
    )
    ax.bar(
        [i + bar_width / 2 for i in positions], own_pct, bar_width,
        label=f"«{own_name}»", color=OWN_COLOR,
    )

    ax.set_ylabel("Доля от максимума на графике, %", color=TEXT_COLOR)
    ax.set_ylim(0, 118)
    ax.set_xlim(-0.7, count - 0.3)
    ax.set_xticks(list(positions))
    ax.set_xticklabels(
        labels, rotation=LABEL_ROTATION, ha="right", rotation_mode="anchor",
        color=TEXT_COLOR,
    )
    ax.tick_params(axis="y", colors=TEXT_COLOR)
    ax.tick_params(axis="x", colors=TEXT_COLOR, length=0)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.25, linewidth=0.6)
    for spine in ("top", "right", "left", "bottom"):
        ax.spines[spine].set_color(GRID_COLOR)
        ax.spines[spine].set_alpha(0.35)

    # The combo half: work types with no deviation to show (own or peer
    # figure missing) leave a break in the line rather than a fake zero or
    # an interpolated segment drawn straight over the missing category —
    # ``nan`` is what makes matplotlib lift the pen instead of connecting
    # across the gap.
    axis2 = ax.twinx()
    if any(d is not None for d in deviations):
        line_y = [d if d is not None else float("nan") for d in deviations]
        axis2.plot(
            list(positions), line_y, color=DEVIATION_COLOR, marker="o", linewidth=1.8,
            markersize=5, label="Отклонение к средней, %",
        )
        axis2.axhline(0, color=DEVIATION_COLOR, alpha=0.3, linewidth=0.8, linestyle="--")
    axis2.set_ylabel("Отклонение от средней, %", color=DEVIATION_COLOR)
    axis2.tick_params(axis="y", colors=DEVIATION_COLOR)
    for spine in axis2.spines.values():
        spine.set_visible(False)

    # Above the plot, not inside it: "upper right" used to sit right where
    # the deviation line peaks for a category dear enough to top the chart,
    # covering the very line the legend is meant to explain.
    bar_handles, bar_labels = ax.get_legend_handles_labels()
    line_handles, line_labels = axis2.get_legend_handles_labels()
    ax.legend(
        bar_handles + line_handles, bar_labels + line_labels,
        loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3,
        frameon=False, labelcolor=TEXT_COLOR,
    )

    buffer = BytesIO()
    # bbox_inches="tight" grows the saved canvas to fit whatever the
    # diagonal labels need instead of guessing a fixed margin — safe now
    # that _short_label bounds how long any one of them can get; unbounded
    # labels were what previously ran this into a canvas thousands of
    # pixels tall.
    fig.savefig(buffer, format="png", transparent=True, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def render_class_average_chart_data_uri(chart_rows, own_name):
    """The same chart, ready to drop straight into an ``<img src>``."""
    png_bytes = render_class_average_chart(chart_rows, own_name)
    return "data:image/png;base64," + b64encode(png_bytes).decode("ascii")
