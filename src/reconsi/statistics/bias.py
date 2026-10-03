"""Systematic (directional) difference detection for paired numeric values."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats


def detect_bias(
    differences: np.ndarray,
    relative_differences: np.ndarray | None = None,
    *,
    alpha: float = 0.01,
    min_pairs: int = 10,
    min_consistency: float = 0.75,
) -> dict[str, Any]:
    """Test whether right-minus-left differences lean consistently in one direction.

    Uses an exact two-sided sign test on the non-zero differences (robust to outliers and to the
    shape of the distribution). A Wilcoxon signed-rank test is reported as supporting evidence.
    Assumes the paired records are independent. A systematic difference is *not* called an error.
    """
    d = differences[np.isfinite(differences)]
    nonzero = d[d != 0]
    n_pos, n_neg = int((nonzero > 0).sum()), int((nonzero < 0).sum())
    out: dict[str, Any] = {
        "pairs": len(d),
        "differing_pairs": len(nonzero),
        "positive": n_pos,
        "negative": n_neg,
        "mean_signed_difference": float(d.mean()) if len(d) else None,
        "median_signed_difference": float(np.median(d)) if len(d) else None,
        "systematic": False,
        "tested": False,
        "label": "observed",
    }
    if len(nonzero) < min_pairs:
        out["reason"] = f"fewer than {min_pairs} differing pairs; no test run"
        return out
    out["tested"] = True
    sign_p = float(stats.binomtest(n_pos, n_pos + n_neg, 0.5).pvalue)
    out["sign_test_p_value"] = sign_p
    try:
        out["wilcoxon_p_value"] = float(stats.wilcoxon(nonzero).pvalue)
    except ValueError:  # pragma: no cover - degenerate input
        out["wilcoxon_p_value"] = None
    mean = float(nonzero.mean())
    if len(nonzero) > 1:
        sem = float(stats.sem(nonzero))
        half = float(stats.t.ppf(0.975, len(nonzero) - 1)) * sem
        out["mean_difference_ci95"] = [mean - half, mean + half]
    consistency = max(n_pos, n_neg) / len(nonzero)
    out["direction"] = "right_higher" if n_pos >= n_neg else "right_lower"
    out["consistency"] = consistency
    if relative_differences is not None:
        rel = relative_differences[np.isfinite(relative_differences) & (relative_differences != 0)]
        if len(rel):
            q1, med, q3 = np.percentile(rel, [25, 50, 75])
            out["median_relative_difference"] = float(med)
            out["relative_iqr"] = float(q3 - q1)
            out["proportional"] = bool(med != 0 and (q3 - q1) <= 0.25 * abs(med))
    q1, q3 = np.percentile(nonzero, [25, 75])
    med_abs = float(np.median(nonzero))
    out["constant_offset"] = bool(med_abs != 0 and (q3 - q1) <= 0.05 * abs(med_abs))
    out["systematic"] = bool(sign_p < alpha and consistency >= min_consistency)
    if out["systematic"]:
        out["label"] = "statistically_supported"
        word = "higher" if out["direction"] == "right_higher" else "lower"
        detail = ""
        if out.get("proportional"):
            detail = f" by a fairly consistent {abs(out['median_relative_difference']) * 100:.2f}%"
        elif out["constant_offset"]:
            detail = f" by a near-constant {abs(med_abs):,.4g}"
        out["message"] = (
            f"Systematic difference detected: the right value is {word}{detail} in "
            f"{consistency:.0%} of {len(nonzero):,} differing pairs (sign test p={sign_p:.2g})."
        )
    return out
