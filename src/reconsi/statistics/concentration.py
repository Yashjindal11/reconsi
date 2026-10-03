"""Where do mismatches concentrate? Breakdowns of record status by categorical dimensions."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from reconsi.comparison.records import DIM_PREFIX, STATUS
from reconsi.core.types import RecordStatus

NULL_LEVEL = "(null)"
STATUSES = [s.value for s in RecordStatus if s is not RecordStatus.AMBIGUOUS]


def _levels(series: pd.Series) -> pd.Series:
    return series.astype(object).where(series.notna(), NULL_LEVEL).astype(str)


def breakdown(records: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Record counts by status for each combination of ``by`` dimension levels."""
    cols = [DIM_PREFIX + d for d in by]
    frame = pd.DataFrame({d: _levels(records[c]) for d, c in zip(by, cols, strict=True)})
    frame[STATUS] = records[STATUS].to_numpy()
    table = frame.groupby([*by, STATUS], sort=False).size().unstack(STATUS, fill_value=0)
    for s in STATUSES:
        if s not in table.columns:
            table[s] = 0
    table = table[STATUSES]
    table.insert(0, "records", table.sum(axis=1))
    table["problems"] = table["records"] - table[RecordStatus.MATCHED.value]
    table["problem_rate"] = table["problems"] / table["records"]
    total_problems = table["problems"].sum()
    table["share_of_problems"] = table["problems"] / total_problems if total_problems else 0.0
    table["share_of_records"] = table["records"] / table["records"].sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        table["lift"] = (table["share_of_problems"] / table["share_of_records"]).fillna(0.0)
    return (
        table.reset_index()
        .sort_values(["problems", "records"], ascending=False, kind="stable")
        .reset_index(drop=True)
    )


def concentration(
    records: pd.DataFrame, dimensions: list[str], alpha: float = 0.01, max_levels: int = 50
) -> list[dict[str, Any]]:
    """Test each dimension for association with record problems (mismatch or missing)."""
    if records.empty or not dimensions:
        return []
    total_problems = int((records[STATUS] != RecordStatus.MATCHED.value).sum())
    out: list[dict[str, Any]] = []
    for dim in dimensions:
        table = breakdown(records, [dim])
        entry: dict[str, Any] = {
            "dimension": dim,
            "levels": table.head(max_levels).to_dict(orient="records"),
            "level_count": len(table),
            "tested": False,
            "concentrated": False,
        }
        if total_problems and len(table) >= 2:
            contingency = np.vstack(
                [table["problems"].to_numpy(), (table["records"] - table["problems"]).to_numpy()]
            )
            contingency = contingency[:, contingency.sum(axis=0) > 0]
            if contingency.shape[1] >= 2 and (contingency.sum(axis=1) > 0).all():
                chi2, p, _, _ = stats.chi2_contingency(contingency)
                n = contingency.sum()
                entry.update(
                    {
                        "tested": True,
                        "chi_square": float(chi2),
                        "p_value": float(p),
                        "p_value_bonferroni": float(min(1.0, p * len(dimensions))),
                        "cramers_v": float(np.sqrt(chi2 / n)) if n else 0.0,
                    }
                )
                top = table.sort_values("share_of_problems", ascending=False).iloc[0]
                entry["top_level"] = {
                    "level": top[dim],
                    "problems": int(top["problems"]),
                    "share_of_problems": float(top["share_of_problems"]),
                    "share_of_records": float(top["share_of_records"]),
                    "problem_rate": float(top["problem_rate"]),
                    "lift": float(top["lift"]),
                }
                entry["concentrated"] = bool(
                    entry["p_value_bonferroni"] < alpha
                    and top["lift"] >= 1.5
                    and top["problems"] >= 5
                )
                if entry["concentrated"]:
                    entry["message"] = (
                        f"{dim} = {top[dim]} accounts for {top['share_of_problems']:.0%} of "
                        f"problem records but only {top['share_of_records']:.0%} of records "
                        f"({top['lift']:.1f}x; problem rate {top['problem_rate']:.1%})."
                    )
        out.append(entry)
    out.sort(key=lambda e: (not e["concentrated"], -float(e.get("cramers_v", 0.0))))
    return out
