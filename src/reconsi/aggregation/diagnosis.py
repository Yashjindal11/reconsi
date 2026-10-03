"""Diagnose whether a mismatch is explained by a difference in grain.

When keys are duplicated on one or both sides, ReconSI aggregates the numeric compare columns per
key on both sides and checks whether the totals agree. If they do, the discrepancy is a grain
(level-of-detail) problem rather than a value problem.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from reconsi.core.dtypes import NUMERIC_TYPES, logical_type
from reconsi.keys.canonical import combined_key


def aggregation_diagnosis(
    left: pd.DataFrame,
    right: pd.DataFrame,
    keys: list[str],
    columns: list[str],
    *,
    absolute_tolerance: float = 0.0,
    relative_tolerance: float = 1e-9,
) -> dict[str, Any] | None:
    numeric = [
        c
        for c in columns
        if c in left.columns
        and c in right.columns
        and logical_type(left[c]) in NUMERIC_TYPES
        and logical_type(right[c]) in NUMERIC_TYPES
    ]
    if not numeric:
        return None
    lk = combined_key(left, keys)
    rk = combined_key(right, keys)
    lsum = left[numeric].groupby(lk.to_numpy()).sum(min_count=1)
    rsum = right[numeric].groupby(rk.to_numpy()).sum(min_count=1)
    common = lsum.index.intersection(rsum.index)
    if len(common) == 0:
        return None
    result: dict[str, Any] = {
        "keys": keys,
        "keys_compared": len(common),
        "left_rows_per_key": float(len(left) / max(1, len(lsum))),
        "right_rows_per_key": float(len(right) / max(1, len(rsum))),
        "columns": {},
        "label": "likely_explanation",
    }
    all_match = True
    for col in numeric:
        a = lsum.loc[common, col].to_numpy(dtype=float)
        b = rsum.loc[common, col].to_numpy(dtype=float)
        tol = np.maximum(absolute_tolerance, relative_tolerance * np.maximum(np.abs(a), np.abs(b)))
        ok = (np.abs(b - a) <= tol) | (np.isnan(a) & np.isnan(b))
        share = float(ok.mean())
        all_match = all_match and share == 1.0
        result["columns"][col] = {
            "keys_matching_after_aggregation": int(ok.sum()),
            "share_matching": share,
            "left_total": float(np.nansum(a)),
            "right_total": float(np.nansum(b)),
            "difference": float(np.nansum(b) - np.nansum(a)),
        }
    result["explained_by_grain"] = all_match
    result["conclusion"] = (
        "No value discrepancy after aggregation: totals per key agree, so the differences are "
        "explained by the datasets being at different grains."
        if all_match
        else "Differences persist after aggregating per key, so grain alone does not explain them."
    )
    return result
