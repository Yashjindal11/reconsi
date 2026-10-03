"""Optional matplotlib charts for notebooks (``pip install "reconsi[report]"``).

Every function accepts an optional ``ax`` and returns the Axes it drew on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from reconsi.core.errors import BackendUnavailableError

if TYPE_CHECKING:
    from reconsi.core.result import ReconciliationResult

INK, OK, WARN, BAD, NEUTRAL = "#1d1d1b", "#2f6b3a", "#a86b00", "#a12a2a", "#5b6f86"


def _axes(ax: Any) -> Any:
    if ax is not None:
        return ax
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise BackendUnavailableError(
            'Plots need matplotlib: pip install "reconsi[report]"'
        ) from exc
    _, new_ax = plt.subplots(figsize=(8, 4))
    return new_ax


def _style(ax: Any, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=11)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def plot_record_status(result: ReconciliationResult, ax: Any = None) -> Any:
    ax = _axes(ax)
    s = result.summary
    labels = ["matched", "value mismatch", "missing from right", "missing from left"]
    values = [
        s["matched_records"],
        s["value_mismatch_records"],
        s["missing_right"],
        s["missing_left"],
    ]
    ax.barh(labels[::-1], values[::-1], color=[BAD, BAD, WARN, OK])
    _style(ax, "Records by status")
    return ax


def plot_column_mismatches(result: ReconciliationResult, ax: Any = None) -> Any:
    ax = _axes(ax)
    stats = sorted(result.columns.values(), key=lambda c: c.mismatch_rate)
    ax.barh([c.column for c in stats], [100 * c.mismatch_rate for c in stats], color=WARN)
    ax.set_xlabel("mismatch rate (%)")
    _style(ax, "Mismatch rate by column")
    return ax


def plot_difference_distribution(
    result: ReconciliationResult, column: str, ax: Any = None, bins: int = 40
) -> Any:
    ax = _axes(ax)
    rows = result.value_mismatches[result.value_mismatches["column"] == column]
    diffs = rows["difference"].to_numpy(dtype=float)
    diffs = diffs[np.isfinite(diffs)]
    ax.hist(diffs, bins=bins, color=NEUTRAL)
    ax.axvline(0, color=INK, linestyle="--", linewidth=1)
    ax.set_xlabel("right - left")
    _style(ax, f"Differences in {column}")
    return ax


def plot_timeline(result: ReconciliationResult, ax: Any = None) -> Any:
    ax = _axes(ax)
    temporal = result.analyses.get("temporal")
    if not temporal:
        _style(ax, "No date column")
        return ax
    periods = [str(p["period"])[:10] for p in temporal["periods"]]
    rates = [100 * p["match_rate"] for p in temporal["periods"]]
    ax.plot(range(len(rates)), rates, color=INK, marker=".")
    for cp in temporal["change_points"]:
        ax.axvline(int(cp["index"]), color=WARN, linestyle="--")
    step = max(1, len(periods) // 8)
    ax.set_xticks(range(0, len(periods), step), periods[::step], rotation=30, ha="right")
    ax.set_ylabel("match rate (%)")
    _style(ax, "Match rate over time")
    return ax


def plot_concentration(result: ReconciliationResult, dimension: str, ax: Any = None) -> Any:
    ax = _axes(ax)
    table = result.drill_down(dimension).sort_values("problem_rate")
    ax.barh(table[dimension].astype(str), 100 * table["problem_rate"], color=WARN)
    ax.set_xlabel("problem rate (%)")
    _style(ax, f"Problem rate by {dimension}")
    return ax


def plot_duplicate_distribution(result: ReconciliationResult, ax: Any = None) -> Any:
    ax = _axes(ax)
    width = 0.4
    for offset, side, color in (
        (-width / 2, result.keys.left, NEUTRAL),
        (width / 2, result.keys.right, WARN),
    ):
        dist = side.multiplicity_distribution
        xs = np.arange(len(dist))
        ax.bar(xs + offset, list(dist.values()), width=width, color=color, label=side.side)
        ax.set_xticks(xs, list(dist.keys()))
    ax.set_xlabel("rows per key")
    ax.set_yscale("log")
    ax.legend(frameon=False)
    _style(ax, "Key multiplicity")
    return ax
