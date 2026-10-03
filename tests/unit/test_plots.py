from __future__ import annotations

import pytest

from reconsi import reconcile
from reconsi.synthetic import generate_reconciliation_pair

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

from reconsi.visualization import plots  # noqa: E402


def test_all_plots_render() -> None:
    import matplotlib.pyplot as plt

    pair = generate_reconciliation_pair(
        3000,
        missing_rate=0.02,
        mismatch_rate=0.02,
        duplicate_rate=0.01,
        incident_days=(10, 14),
        seed=1,
    )
    result = reconcile(pair.left, pair.right, keys="order_id", duplicate_strategy="first")
    for fn, args in (
        (plots.plot_record_status, ()),
        (plots.plot_column_mismatches, ()),
        (plots.plot_difference_distribution, ("revenue",)),
        (plots.plot_timeline, ()),
        (plots.plot_concentration, ("region",)),
        (plots.plot_duplicate_distribution, ()),
    ):
        ax = fn(result, *args)
        assert ax.get_title(loc="left")
    plt.close("all")
