"""Example 1: two CSV daily reports that should agree, but don't.

Report A comes from the sales system, report B from the data warehouse. B was produced with an
extraction filter that silently dropped one store, and its revenue column is rounded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from _common import out_dir

from reconsi import reconcile


def main() -> None:
    out = out_dir("01_csv_reports")
    rng = np.random.default_rng(1)
    stores = [f"S{i:03d}" for i in range(1, 41)]
    products = [f"P{i:02d}" for i in range(1, 26)]
    a = pd.DataFrame(
        [
            (s, p, round(float(rng.uniform(50, 900)), 2), int(rng.integers(1, 40)))
            for s in stores
            for p in products
        ],
        columns=["store_id", "product_id", "revenue", "units"],
    )
    b = a[a["store_id"] != "S017"].copy()
    b["revenue"] = b["revenue"].round(0)
    a.to_csv(out / "report_a.csv", index=False)
    b.to_csv(out / "report_b.csv", index=False)

    result = reconcile(out / "report_a.csv", out / "report_b.csv", keys=["store_id", "product_id"])
    print(result)
    for f in result.findings[:6]:
        print(f" - [{f.evidence.value}] {f.title}")

    tolerant = reconcile(
        out / "report_a.csv",
        out / "report_b.csv",
        keys=["store_id", "product_id"],
        columns={"revenue": {"absolute_tolerance": 0.5}},
    )
    print("with a 0.5 tolerance on revenue:", tolerant)
    print(
        tolerant.drill_down("store_id").head(3)[
            ["store_id", "records", "missing_right", "problem_rate"]
        ]
    )
    tolerant.to_html(out / "report.html")


if __name__ == "__main__":
    main()
