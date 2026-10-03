"""Confidence intervals and small statistical helpers."""

from __future__ import annotations

import math

import numpy as np
from scipy import stats


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (well-behaved near 0 and 1)."""
    if n <= 0:
        return (0.0, 1.0)
    z = float(stats.norm.ppf(0.5 + confidence / 2))
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    lo = 0.0 if successes == 0 else max(0.0, centre - half)
    hi = 1.0 if successes == n else min(1.0, centre + half)
    return (lo, hi)


PERCENTILES: tuple[int, ...] = (1, 5, 25, 50, 75, 95, 99)


def describe_differences(values: np.ndarray) -> dict[str, float | int | None]:
    """Distribution summary of signed differences (NaNs ignored)."""
    v = values[np.isfinite(values)]
    n = len(v)
    out: dict[str, float | int | None] = {"count": n}
    if n == 0:
        return out
    pct = np.percentile(v, PERCENTILES)
    out.update(
        {
            "mean": float(v.mean()),
            "median": float(pct[3]),
            "std": float(v.std(ddof=1)) if n > 1 else 0.0,
            "min": float(v.min()),
            "max": float(v.max()),
            "mean_absolute": float(np.abs(v).mean()),
            "sum": float(v.sum()),
            "positive": int((v > 0).sum()),
            "negative": int((v < 0).sum()),
            "zero": int((v == 0).sum()),
        }
    )
    for p, q in zip(PERCENTILES, pct, strict=True):
        out[f"p{p:02d}"] = float(q)
    return out
