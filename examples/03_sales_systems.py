"""Example 3: two sales systems with different column names and formatting.

The CRM and the billing system describe the same orders with different names
(`cust_id` vs `customer_id`, `sales_amt` vs `sales_amount`, `txn_dt` vs `transaction_date`),
and billing stores customer names upper-cased.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from _common import out_dir

from reconsi import reconcile
from reconsi.schema import compare_schemas


def main() -> None:
    out = out_dir("03_sales_systems")
    rng = np.random.default_rng(3)
    n = 5_000
    crm = pd.DataFrame(
        {
            "order_id": np.arange(n),
            "customer_id": rng.integers(1000, 2000, n),
            "customer_name": rng.choice(["Acme Ltd", "Globex Inc", "Initech LLC"], n),
            "sales_amount": rng.uniform(10, 500, n).round(2),
            "transaction_date": pd.Timestamp("2026-09-01")
            + pd.to_timedelta(rng.integers(0, 30, n), unit="D"),
        }
    )
    billing = crm.rename(
        columns={
            "customer_id": "cust_id",
            "sales_amount": "sales_amt",
            "transaction_date": "txn_dt",
        }
    )
    billing["customer_name"] = billing["customer_name"].str.upper()
    billing.loc[billing.sample(40, random_state=1).index, "sales_amt"] += 5

    # Step 1: ReconSI suggests (but never applies) the column mapping.
    diff = compare_schemas(crm, billing)
    for s in diff.suggestions:
        print(f"suggested: {s.left} <-> {s.right}  (score {s.score:.2f})")
    mapping = {s.left: s.right for s in diff.suggestions}

    # Step 2: apply the mapping we agree with, and decide how names should compare.
    result = reconcile(
        crm,
        billing,
        keys="order_id",
        column_mapping=mapping,
        columns={"customer_name": {"normalize": ["trim", "casefold"]}},
    )
    print(result)
    print(result.column_statistics[["column", "classification", "mismatches", "within_tolerance"]])
    result.to_html(out / "report.html")


if __name__ == "__main__":
    main()
