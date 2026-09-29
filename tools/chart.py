"""Render charts for the territory report. Owned by the main agent.

Charts are rendered in code from numbers the analyst returned, so a chart can never show
a figure the model made up. The PNG lands in ``output/`` and the HTML report embeds it by
file name.
"""

from __future__ import annotations

import re

from langchain.tools import tool

from config import OUTPUT_DIR


def _safe_name(filename: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.strip()).strip("-") or "chart"
    return name if name.endswith(".png") else f"{name}.png"


@tool
def render_bar_chart(filename: str, title: str, labels: list[str], values: list[float], value_label: str = "USD") -> str:
    """Render a horizontal bar chart to output/<filename>.png and return its file name.

    Pass parallel lists: labels (e.g. countries) and values (e.g. revenue). Keep it to at
    most 12 bars. Reference the returned file name from write_html_report with
    '![title](filename.png)'.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not labels or len(labels) != len(values):
        return "Error: labels and values must be non-empty lists of the same length."
    pairs = sorted(zip(labels, values), key=lambda p: p[1])[-12:]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / _safe_name(filename)

    fig, ax = plt.subplots(figsize=(8, 0.45 * len(pairs) + 1.4), dpi=150)
    ax.barh([p[0] for p in pairs], [p[1] for p in pairs], color="#1f6feb")
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
    ax.set_xlabel(value_label)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", color="#e3e7ee")
    ax.set_axisbelow(True)
    for y, (_, v) in enumerate(pairs):
        ax.text(v, y, f" {v:,.0f}" if v >= 100 else f" {v:,.2f}", va="center", fontsize=8, color="#5b6573")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return f"Rendered {path.name} ({len(pairs)} bars). Embed it with ![{title}]({path.name})"


CHART_TOOLS = [render_bar_chart]
