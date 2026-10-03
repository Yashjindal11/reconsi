"""Example 4: raw transactions vs. daily aggregates, done naively and done right.

Comparing order-level data to a daily summary row by row makes almost everything look wrong.
ReconSI diagnoses the grain problem, and the grain-aware comparison finds the one real issue.
"""

from __future__ import annotations

from _common import out_dir

from reconsi import reconcile
from reconsi.synthetic import generate_base


def main() -> None:
    out = out_dir("04_aggregated_vs_raw")
    orders = generate_base(30_000, days=30, seed=4)
    daily = orders.groupby("date", as_index=False).agg(
        revenue=("revenue", "sum"), orders=("order_id", "size")
    )
    daily["revenue"] = daily["revenue"].round(2)
    daily.loc[daily["date"] == "2026-09-18", "orders"] -= (
        3  # three orders never reached the summary
    )

    naive = reconcile(orders, daily, keys="date", compare_columns=["revenue"])
    print("naive:", naive)
    print(
        "grain:",
        naive.analyses["grain"]["left"]["description"],
        "vs",
        naive.analyses["grain"]["right"]["description"],
    )
    print("diagnosis:", naive.analyses["aggregation_diagnosis"]["conclusion"])

    aware = reconcile(
        orders,
        daily,
        left_group_by=["date"],
        aggregations={"revenue": "sum", "orders": "count"},
        absolute_tolerance=0.01,
    )
    print("grain-aware:", aware)
    print(aware.value_mismatches[["date", "column", "left_value", "right_value", "difference"]])
    aware.to_html(out / "report.html")


if __name__ == "__main__":
    main()
