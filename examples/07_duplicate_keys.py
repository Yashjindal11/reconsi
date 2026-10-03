"""Example 7: how a many-to-many join inflates totals.

Orders and shipments are both keyed by `order_id`, and both have several rows per order (order
lines; split shipments). Joining them and summing gives a total that matches neither source.
"""

from __future__ import annotations

import pandas as pd
from _common import out_dir

from reconsi import reconcile


def main() -> None:
    out = out_dir("07_duplicate_keys")
    order_lines = pd.DataFrame(
        {"order_id": [1, 1, 1, 2, 3, 3], "amount": [40.0, 25.0, 35.0, 80.0, 10.0, 20.0]}
    )
    shipments = pd.DataFrame(
        {"order_id": [1, 1, 2, 3, 3, 3], "amount": [60.0, 40.0, 80.0, 10.0, 10.0, 10.0]}
    )

    joined = order_lines.merge(shipments, on="order_id", suffixes=("_ordered", "_shipped"))
    print("order total:", order_lines["amount"].sum(), "shipment total:", shipments["amount"].sum())
    print(
        "total after a naive join:", joined["amount_ordered"].sum(), f"({len(joined)} joined rows)"
    )

    result = reconcile(order_lines, shipments, keys="order_id")
    print(result)
    risk = next(f for f in result.findings if f.title == "Many-to-many reconciliation risk")
    print(risk.detail)
    print(result.duplicate_keys)

    fixed = reconcile(order_lines, shipments, keys="order_id", duplicate_strategy="aggregate")
    print("after aggregating per order:", fixed)
    fixed.to_markdown(out / "report.md")


if __name__ == "__main__":
    main()
