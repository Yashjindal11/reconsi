"""Change-point detection for a sequence of binomial proportions (problem records per period).

Binary segmentation with a binomial likelihood-ratio statistic. Each candidate split is tested
with a permutation test (shuffling period order within the segment), so no distributional
approximation of the max-statistic is needed. A detected change point says *when* the rate
changed, never *why*.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _loglik(k: np.ndarray, n: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        p = np.where(n > 0, k / n, 0.0)
        a = np.where(k > 0, k * np.log(np.where(p > 0, p, 1.0)), 0.0)
        b = np.where(n - k > 0, (n - k) * np.log(np.where(p < 1, 1 - p, 1.0)), 0.0)
    return np.asarray(a + b)


def _split_statistics(k: np.ndarray, n: np.ndarray, min_size: int) -> np.ndarray:
    """Log-likelihood ratio for every admissible split position (index = first right period)."""
    ck, cn = np.cumsum(k), np.cumsum(n)
    total = _loglik(ck[-1:], cn[-1:])[0]
    t = np.arange(min_size, len(k) - min_size + 1)
    left = _loglik(ck[t - 1], cn[t - 1])
    right = _loglik(ck[-1] - ck[t - 1], cn[-1] - cn[t - 1])
    return np.asarray(left + right - total)


def detect_change_points(
    problems: np.ndarray,
    records: np.ndarray,
    *,
    alpha: float = 0.01,
    min_size: int = 3,
    max_points: int = 3,
    permutations: int = 499,
    seed: int = 0,
) -> list[dict[str, Any]]:
    k = np.asarray(problems, dtype=float)
    n = np.asarray(records, dtype=float)
    rng = np.random.default_rng(seed)
    found: list[dict[str, Any]] = []
    stack = [(0, len(k))]
    while stack and len(found) < max_points:
        start, end = stack.pop(0)
        sk, sn = k[start:end], n[start:end]
        if end - start < 2 * min_size or sk.sum() == 0 or sk.sum() == sn.sum():
            continue
        stats = _split_statistics(sk, sn, min_size)
        best = int(np.argmax(stats))
        observed = float(stats[best])
        if observed <= 0:
            continue
        exceed = 0
        for _ in range(permutations):
            perm = rng.permutation(len(sk))
            if _split_statistics(sk[perm], sn[perm], min_size).max() >= observed:
                exceed += 1
        p = (exceed + 1) / (permutations + 1)
        if p >= alpha:
            continue
        split = start + min_size + best
        before = float(k[start:split].sum()) / max(1.0, float(n[start:split].sum()))
        after = float(k[split:end].sum()) / max(1.0, float(n[split:end].sum()))
        found.append(
            {
                "index": split,
                "log_likelihood_ratio": observed,
                "p_value": p,
                "rate_before": float(before),
                "rate_after": float(after),
                "segment": [start, end],
            }
        )
        stack.extend([(start, split), (split, end)])
    found.sort(key=lambda d: int(d["index"]))
    return found
