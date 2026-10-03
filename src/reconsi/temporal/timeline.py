"""Reconciliation quality over time."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from reconsi.comparison.records import DATE, STATUS
from reconsi.core.profiling import to_period
from reconsi.core.serialization import frame_records
from reconsi.core.types import RecordStatus
from reconsi.temporal.changepoint import detect_change_points, segments

STATUSES = [s.value for s in RecordStatus if s is not RecordStatus.AMBIGUOUS]


def timeline_table(records: pd.DataFrame, frequency: str = "D") -> pd.DataFrame:
    period = to_period(records[DATE], frequency)
    frame = pd.DataFrame({"period": period, STATUS: records[STATUS].to_numpy()})
    frame = frame[frame["period"].notna()]
    table = frame.groupby(["period", STATUS]).size().unstack(STATUS, fill_value=0)
    for s in STATUSES:
        if s not in table.columns:
            table[s] = 0
    table = table[STATUSES].sort_index()
    table.insert(0, "records", table.sum(axis=1))
    table["problems"] = table["records"] - table[RecordStatus.MATCHED.value]
    table["match_rate"] = table[RecordStatus.MATCHED.value] / table["records"]
    table["problem_rate"] = table["problems"] / table["records"]
    return table.reset_index()


def timeline(
    records: pd.DataFrame,
    *,
    frequency: str = "D",
    alpha: float = 0.01,
    seed: int = 0,
) -> dict[str, Any] | None:
    """Match rate per period, anomalous periods and change points in the problem rate."""
    if DATE not in records.columns or records.empty:
        return None
    table = timeline_table(records, frequency)
    unparsed = int(len(records) - table["records"].sum())
    if table.empty:
        return None
    k = table["problems"].to_numpy(dtype=float)
    n = table["records"].to_numpy(dtype=float)
    detected = detect_change_points(k, n, alpha=alpha, seed=seed)
    # Anomalies are judged against the other periods of the same regime, so that a sustained
    # level shift is reported once as a change point rather than as many anomalous days.
    anomalies: list[dict[str, Any]] = []
    total_k, total_n = k.sum(), n.sum()
    for lo, hi in segments(len(table), detected):
        seg_k, seg_n = k[lo:hi].sum(), n[lo:hi].sum()
        for i in range(lo, hi):
            rest_n = seg_n - n[i]
            if hi - lo < 3 or rest_n <= 0 or k[i] < 5:
                continue
            baseline = (seg_k - k[i]) / rest_n
            rate = k[i] / n[i]
            p = float(stats.binomtest(int(k[i]), int(n[i]), max(baseline, 1e-9), "greater").pvalue)
            p_adj = min(1.0, p * len(table))
            if p_adj < alpha and rate >= 2 * baseline:
                anomalies.append(
                    {
                        "period": table["period"].iloc[i],
                        "problem_rate": float(rate),
                        "baseline_rate": float(baseline),
                        "p_value_bonferroni": p_adj,
                    }
                )
    change_points = [{**cp, "period": table["period"].iloc[int(cp["index"])]} for cp in detected]
    for cp in change_points:
        cp["message"] = (
            f"Problem rate changed significantly around {pd.Timestamp(cp['period']).date()} "
            f"({cp['rate_before']:.2%} before, {cp['rate_after']:.2%} after). "
            "This identifies when, not why."
        )
    return {
        "frequency": frequency,
        "periods": frame_records(table),
        "unparsed_dates": unparsed,
        "anomalous_periods": anomalies,
        "change_points": change_points,
        "overall_problem_rate": float(total_k / total_n) if total_n else 0.0,
        "trend_slope_per_period": _slope(k, n),
    }


def _slope(k: np.ndarray, n: np.ndarray) -> float | None:
    if len(k) < 3:
        return None
    rates = k / np.maximum(n, 1)
    x = np.arange(len(rates), dtype=float)
    return float(np.polyfit(x, rates, 1, w=np.sqrt(n))[0])
