"""Compare the distributions of a column across the two datasets (no row matching required).

Large samples make almost any difference "significant", so a shift is flagged only when the
p-value is below ``alpha`` *and* an effect size exceeds a practical threshold.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial.distance import jensenshannon

from reconsi.core.dtypes import NUMERIC_TYPES, TEMPORAL_TYPES, logical_type

KS_EFFECT = 0.1
SMD_EFFECT = 0.2
JSD_EFFECT = 0.02
CRAMERS_V_EFFECT = 0.1


def _numeric(values: pd.Series) -> np.ndarray:
    arr: np.ndarray = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    return np.asarray(arr[np.isfinite(arr)])


def numeric_distribution(left: pd.Series, right: pd.Series, alpha: float) -> dict[str, Any]:
    a, b = _numeric(left), _numeric(right)
    out: dict[str, Any] = {"type": "numeric", "left_n": len(a), "right_n": len(b)}
    for name, arr in (("left", a), ("right", b)):
        if len(arr):
            q = np.percentile(arr, [5, 25, 50, 75, 95])
            out[name] = {
                "mean": float(arr.mean()),
                "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
                "variance": float(arr.var(ddof=1)) if len(arr) > 1 else 0.0,
                "min": float(arr.min()),
                "p05": float(q[0]),
                "p25": float(q[1]),
                "median": float(q[2]),
                "p75": float(q[3]),
                "p95": float(q[4]),
                "max": float(arr.max()),
            }
    if len(a) < 2 or len(b) < 2:
        out["tested"] = False
        out["shift"] = False
        return out
    ks = stats.ks_2samp(a, b)
    pooled = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    smd = float((b.mean() - a.mean()) / pooled) if pooled > 0 else 0.0
    wd = float(stats.wasserstein_distance(a, b))
    out.update(
        {
            "tested": True,
            "ks_statistic": float(ks.statistic),
            "ks_p_value": float(ks.pvalue),
            "wasserstein_distance": wd,
            "wasserstein_normalized": wd / pooled if pooled > 0 else 0.0,
            "standardized_mean_difference": smd,
        }
    )
    out["shift"] = bool(ks.pvalue < alpha and (ks.statistic >= KS_EFFECT or abs(smd) >= SMD_EFFECT))
    return out


def categorical_distribution(
    left: pd.Series, right: pd.Series, alpha: float, max_levels: int = 30
) -> dict[str, Any]:
    lc = left.astype(object).where(left.notna(), "(null)").astype(str).value_counts()
    rc = right.astype(object).where(right.notna(), "(null)").astype(str).value_counts()
    table = pd.concat([lc.rename("left"), rc.rename("right")], axis=1).fillna(0)
    table = table.sort_values(["left", "right"], ascending=False)
    if len(table) > max_levels:
        top = table.iloc[: max_levels - 1]
        other = table.iloc[max_levels - 1 :].sum().rename("(other)")
        table = pd.concat([top, other.to_frame().T])
    lt, rt = table["left"].sum(), table["right"].sum()
    levels = [
        {
            "level": str(idx),
            "left_count": int(row["left"]),
            "right_count": int(row["right"]),
            "left_share": float(row["left"] / lt) if lt else 0.0,
            "right_share": float(row["right"] / rt) if rt else 0.0,
        }
        for idx, row in table.iterrows()
    ]
    out: dict[str, Any] = {
        "type": "categorical",
        "left_n": int(lt),
        "right_n": int(rt),
        "levels": levels,
    }
    if lt == 0 or rt == 0 or len(table) < 2:
        out["tested"] = False
        out["shift"] = False
        return out
    jsd = float(jensenshannon(table["left"] / lt, table["right"] / rt, base=2) ** 2)
    chi2, p, dof, _ = stats.chi2_contingency(table[["left", "right"]].to_numpy().T)
    v = float(np.sqrt(chi2 / (lt + rt))) if (lt + rt) else 0.0
    out.update(
        {
            "tested": True,
            "chi_square": float(chi2),
            "chi_square_dof": int(dof),
            "chi_square_p_value": float(p),
            "cramers_v": v,
            "jensen_shannon_divergence": jsd,
        }
    )
    out["shift"] = bool(p < alpha and (jsd >= JSD_EFFECT or v >= CRAMERS_V_EFFECT))
    return out


def compare_distributions(
    left: pd.DataFrame, right: pd.DataFrame, columns: list[str], alpha: float = 0.01
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in columns:
        if col not in left.columns or col not in right.columns:
            continue
        lt, rt = logical_type(left[col]), logical_type(right[col])
        if lt in NUMERIC_TYPES and rt in NUMERIC_TYPES:
            out[col] = numeric_distribution(left[col], right[col], alpha)
        elif lt in TEMPORAL_TYPES or rt in TEMPORAL_TYPES or "float" in (lt, rt):
            continue
        else:
            n_levels = max(left[col].nunique(), right[col].nunique())
            if n_levels <= 1000:
                out[col] = categorical_distribution(left[col], right[col], alpha)
    return out
