"""Example 6: daily reconciliation over a month - when did it start going wrong?

From 14 September a pipeline change starts corrupting about a quarter of revenue values; the
problem is fixed on the 18th. ReconSI finds both boundaries of the incident.
"""

from __future__ import annotations

from _common import out_dir

from reconsi import reconcile
from reconsi.synthetic import generate_reconciliation_pair


def main() -> None:
    out = out_dir("06_time_based")
    pair = generate_reconciliation_pair(
        30_000, incident_days=(13, 17), incident_rate=0.25, mismatch_rate=0.002, seed=6
    )
    result = reconcile(pair.left, pair.right, keys="order_id")
    temporal = result.analyses["temporal"]
    for period in temporal["periods"][10:20]:
        print(f"{str(period['period'])[:10]}  match {100 * period['match_rate']:6.2f}%")
    for cp in temporal["change_points"]:
        print(cp["message"])
    print("injected incident:", pair.truth.incident_dates)
    result.to_html(out / "report.html")


if __name__ == "__main__":
    main()
