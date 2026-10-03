"""Example 2: finance reconciliation - transaction-level ledger vs. a monthly financial summary.

The ledger has one row per transaction; finance publishes totals per account and month. One
account's September total is off because a reversal was booked twice.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from _common import out_dir

from reconsi import reconcile


def main() -> None:
    out = out_dir("02_finance")
    rng = np.random.default_rng(2)
    n = 20_000
    ledger = pd.DataFrame(
        {
            "transaction_id": [f"T{i:07d}" for i in range(n)],
            "account": rng.choice(["4000-Sales", "4100-Services", "5000-COGS", "6100-Travel"], n),
            "month": rng.choice(["2026-07", "2026-08", "2026-09"], n),
            "amount": rng.normal(250, 120, n).round(2),
        }
    )
    summary = ledger.groupby(["account", "month"], as_index=False).agg(
        amount=("amount", "sum"), transactions=("transaction_id", "size")
    )
    summary["amount"] = summary["amount"].round(2)
    bad = (summary["account"] == "6100-Travel") & (summary["month"] == "2026-09")
    summary.loc[bad, "amount"] -= 412.50

    result = reconcile(
        ledger,
        summary,
        left_group_by=["account", "month"],
        aggregations={"amount": "sum", "transactions": "count"},
        columns={"amount": {"absolute_tolerance": 0.01, "critical": True}},
        name="ledger_vs_summary",
    )
    print(result)
    print(
        result.value_mismatches[
            ["account", "month", "column", "left_value", "right_value", "difference"]
        ]
    )
    result.to_markdown(out / "report.md")


if __name__ == "__main__":
    main()
