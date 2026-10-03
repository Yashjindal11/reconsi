"""Change-point detection for a sequence of binomial proportions (problem records per period).

Circular binary segmentation (CBS, Olshen et al. 2004) with a binomial likelihood-ratio
statistic: within a segment, find the sub-interval whose problem rate differs most from the rest
of the segment. Unlike plain binary segmentation this also catches temporary regimes (a rate
that rises and later falls back). Significance comes from a permutation test that shuffles period
order within the segment, so no approximation of the max-statistic is needed. A detected change
point says *when* the rate changed, never *why*.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import numpy as np


def _loglik(k: np.ndarray, n: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        p = np.where(n > 0, k / n, 0.0)
        a = np.where(k > 0, k * np.log(np.where(p > 0, p, 1.0)), 0.0)
        b = np.where(n - k > 0, (n - k) * np.log(np.where(p < 1, 1 - p, 1.0)), 0.0)
    return np.asarray(a + b)


def _pairs(length: int, min_size: int) -> tuple[np.ndarray, np.ndarray]:
    """All (i, j) with an inside interval [i, j) and an outside part of at least ``min_size``."""
    i, j = np.triu_indices(length + 1, k=min_size)
    inside = j - i
    keep = (length - inside >= min_size) & (inside >= min_size)
    return i[keep], j[keep]


def _cbs_statistic(
    k: np.ndarray, n: np.ndarray, pairs: tuple[np.ndarray, np.ndarray]
) -> tuple[float, int]:
    ck = np.concatenate([[0.0], np.cumsum(k)])
    cn = np.concatenate([[0.0], np.cumsum(n)])
    i, j = pairs
    k_in, n_in = ck[j] - ck[i], cn[j] - cn[i]
    k_out, n_out = ck[-1] - k_in, cn[-1] - n_in
    total = _loglik(ck[-1:], cn[-1:])[0]
    llr = _loglik(k_in, n_in) + _loglik(k_out, n_out) - total
    best = int(np.argmax(llr))
    return float(llr[best]), best


def _rate(k: np.ndarray, n: np.ndarray) -> float:
    return float(k.sum()) / max(1.0, float(n.sum()))


def detect_change_points(
    problems: np.ndarray,
    records: np.ndarray,
    *,
    alpha: float = 0.01,
    min_size: int = 3,
    max_points: int = 6,
    permutations: int = 499,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Return change points sorted by position; ``index`` is the first period of the new regime."""
    k = np.asarray(problems, dtype=float)
    n = np.asarray(records, dtype=float)
    rng = np.random.default_rng(seed)
    boundaries: dict[int, dict[str, Any]] = {}
    stack = [(0, len(k))]
    while stack and len(boundaries) < max_points:
        start, end = stack.pop(0)
        sk, sn = k[start:end], n[start:end]
        length = end - start
        if length < 2 * min_size or sk.sum() == 0 or sk.sum() == sn.sum():
            continue
        pairs = _pairs(length, min_size)
        if len(pairs[0]) == 0:
            continue
        observed, best = _cbs_statistic(sk, sn, pairs)
        if observed <= 1e-9:
            continue
        reps = permutations if length <= 200 else min(permutations, 199)
        exceed = 0
        for _ in range(reps):
            perm = rng.permutation(length)
            if _cbs_statistic(sk[perm], sn[perm], pairs)[0] >= observed:
                exceed += 1
        p = (exceed + 1) / (reps + 1)
        if p >= alpha:
            continue
        i, j = start + int(pairs[0][best]), start + int(pairs[1][best])
        cuts = [c for c in (i, j) if start < c < end]
        edges = [start, *cuts, end]
        for c_idx, cut in enumerate(cuts, 1):
            lo, hi = edges[c_idx - 1], edges[c_idx + 1]
            boundaries[cut] = {
                "index": cut,
                "log_likelihood_ratio": observed,
                "p_value": p,
                "rate_before": _rate(k[lo:cut], n[lo:cut]),
                "rate_after": _rate(k[cut:hi], n[cut:hi]),
            }
        stack.extend(pairwise(edges))
    return [boundaries[c] for c in sorted(boundaries)]


def segments(length: int, change_points: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Split ``range(length)`` into the regimes delimited by ``change_points``."""
    edges = [0, *sorted(int(cp["index"]) for cp in change_points), length]
    return list(pairwise(edges))
