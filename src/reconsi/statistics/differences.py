"""Rank the largest individual differences of numeric columns."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from reconsi.core.serialization import frame_records

RankBy = Literal["absolute", "relative", "positive", "negative"]


def largest_differences(
    mismatches: pd.DataFrame, column: str, n: int = 10, by: RankBy = "absolute"
) -> pd.DataFrame:
    rows = mismatches[mismatches["column"] == column]
    diff = pd.to_numeric(rows["difference"], errors="coerce")
    rows = rows[np.isfinite(diff.to_numpy(dtype=float, na_value=np.nan))]
    diff = pd.to_numeric(rows["difference"], errors="coerce")
    if by == "absolute":
        order = diff.abs().sort_values(ascending=False, kind="stable").index
    elif by == "relative":
        rel = pd.to_numeric(rows["relative_difference"], errors="coerce").abs()
        order = rel.dropna().sort_values(ascending=False, kind="stable").index
    elif by == "positive":
        order = diff[diff > 0].sort_values(ascending=False, kind="stable").index
    elif by == "negative":
        order = diff[diff < 0].sort_values(ascending=True, kind="stable").index
    else:
        raise ValueError(f"by must be absolute, relative, positive or negative, not {by!r}")
    return rows.loc[order].head(n).reset_index(drop=True)


def largest_differences_summary(
    mismatches: pd.DataFrame, columns: list[str], n: int = 5
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in columns:
        entry = {
            by: frame_records(largest_differences(mismatches, col, n, by))
            for by in ("absolute", "relative", "positive", "negative")
        }
        if any(entry.values()):
            out[col] = entry
    return out
