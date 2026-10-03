"""Is the population of missing records systematically different from the matched population?"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from reconsi.comparison.records import DATE, DIM_PREFIX, STATUS
from reconsi.core.types import RecordStatus
from reconsi.statistics.concentration import NULL_LEVEL

_PRESENT_ON = {
    "left": (
        RecordStatus.MISSING_RIGHT.value,
        {RecordStatus.MATCHED.value, RecordStatus.VALUE_MISMATCH.value},
    ),
    "right": (
        RecordStatus.MISSING_LEFT.value,
        {RecordStatus.MATCHED.value, RecordStatus.VALUE_MISMATCH.value},
    ),
}


def _compare_levels(
    missing: pd.Series, present: pd.Series, alpha: float, n_tests: int
) -> dict[str, Any] | None:
    mc = missing.value_counts()
    pc = present.value_counts()
    table = pd.concat([mc.rename("missing"), pc.rename("present")], axis=1).fillna(0)
    if len(table) < 2 or table["missing"].sum() < 5 or table["present"].sum() < 5:
        return None
    chi2, p, _, _ = stats.chi2_contingency(table.to_numpy().T)
    shares = table / table.sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        lift = (shares["missing"] / shares["present"]).replace(np.inf, np.nan)
    over = shares.assign(lift=lift).sort_values("missing", ascending=False)
    over = over[(over["missing"] > over["present"]) & (table.loc[over.index, "missing"] >= 3)]
    p_adj = min(1.0, float(p) * n_tests)
    n = table.to_numpy().sum()
    v = float(np.sqrt(chi2 / n)) if n else 0.0
    return {
        "p_value": float(p),
        "p_value_bonferroni": p_adj,
        "cramers_v": v,
        "significant": bool(p_adj < alpha and v >= 0.1),
        "over_represented": [
            {
                "level": str(level),
                "share_of_missing": float(row["missing"]),
                "share_of_present": float(row["present"]),
                "lift": None if pd.isna(row["lift"]) else float(row["lift"]),
            }
            for level, row in over.head(5).iterrows()
        ],
    }


def unmatched_population(
    records: pd.DataFrame,
    dimensions: list[str],
    *,
    date_frequency: str | None = "M",
    alpha: float = 0.01,
) -> dict[str, Any]:
    """For each side, compare records missing from the other side against those that matched."""
    out: dict[str, Any] = {}
    if records.empty:
        return out
    columns: dict[str, pd.Series] = {
        d: records[DIM_PREFIX + d].astype(object).where(records[DIM_PREFIX + d].notna(), NULL_LEVEL)
        for d in dimensions
    }
    if DATE in records.columns and date_frequency:
        from reconsi.core.profiling import to_period

        period = to_period(records[DATE], date_frequency)
        columns["period"] = period.astype(str).where(period.notna(), NULL_LEVEL)
    n_tests = max(1, len(columns))
    status = records[STATUS]
    for side, (missing_status, present_statuses) in _PRESENT_ON.items():
        missing_mask = (status == missing_status).to_numpy()
        present_mask = status.isin(present_statuses).to_numpy()
        if missing_mask.sum() < 5:
            continue
        label = "missing_from_right" if side == "left" else "missing_from_left"
        findings: list[dict[str, Any]] = []
        for name, values in columns.items():
            res = _compare_levels(
                values[missing_mask].astype(str), values[present_mask].astype(str), alpha, n_tests
            )
            if res is not None:
                findings.append({"dimension": name, **res})
        findings.sort(key=lambda f: (not f["significant"], -f["cramers_v"]))
        out[label] = {"missing_records": int(missing_mask.sum()), "dimensions": findings}
    return out
