"""Infer the grain (the set of columns that uniquely identifies a row) of a dataset.

The result is always an *inference* from the observed data: a combination that happens to be
unique in this extract is not guaranteed to be unique by design.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

from reconsi.core.dtypes import logical_type

GRAIN_TYPES = frozenset(
    {"string", "categorical", "integer", "date", "datetime", "datetime_tz", "boolean"}
)


@dataclass
class GrainInference:
    side: str
    rows: int
    columns: list[str] | None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    sampled: bool = False

    @property
    def description(self) -> str:
        if not self.columns:
            return "no unique combination of up to three columns was found"
        return " + ".join(self.columns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "rows": self.rows,
            "columns": self.columns,
            "description": self.description,
            "evidence": self.evidence,
            "sampled": self.sampled,
            "label": "inference",
        }


def _duplicate_rows(frame: pd.DataFrame, cols: list[str]) -> int:
    return int(frame.duplicated(subset=cols).sum())


_ID_TOKENS = frozenset({"id", "key", "code", "number", "no", "num", "uuid", "guid", "sku"})


def _id_like(name: str) -> bool:
    tokens = re.split(r"[^0-9a-z]+", re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name).lower())
    return any(t in _ID_TOKENS for t in tokens)


def infer_grain(
    frame: pd.DataFrame,
    *,
    side: str = "table",
    total_rows: int | None = None,
    exclude: set[str] | None = None,
    max_columns: int = 3,
    max_candidates: int = 12,
    verify: Callable[[list[str]], bool] | None = None,
) -> GrainInference:
    """Find the smallest column combination that is unique in ``frame``.

    ``frame`` may be a sample; pass ``verify`` to confirm uniqueness on the full data and
    ``total_rows`` for reporting. Float columns (measures) are never considered.
    """
    exclude = exclude or set()
    rows = len(frame) if total_rows is None else total_rows
    candidates: list[tuple[str, int]] = []
    for col in frame.columns:
        name = str(col)
        if name in exclude or logical_type(frame[name]) not in GRAIN_TYPES:
            continue
        n = int(frame[name].nunique(dropna=False))
        if n > 1 or len(frame) <= 1:
            candidates.append((name, n))
    candidates = candidates[:max_candidates]
    cardinality = dict(candidates)
    names = [c for c, _ in candidates]
    evidence: list[dict[str, Any]] = []
    for size in range(1, max_columns + 1):
        unique_combos: list[tuple[float, list[str]]] = []
        near: list[tuple[int, list[str]]] = []
        for combo in combinations(names, size):
            cols = list(combo)
            if size > 1 and np.prod([float(cardinality[c]) for c in cols]) < len(frame):
                continue
            dups = _duplicate_rows(frame, cols)
            if dups == 0:
                unique_combos.append((float(np.prod([float(cardinality[c]) for c in cols])), cols))
            else:
                near.append((dups, cols))
        near.sort(key=lambda t: t[0])
        for dups, cols in near[:2]:
            evidence.append({"columns": cols, "unique": False, "duplicate_rows": dups})
        for _, cols in sorted(
            unique_combos,
            key=lambda t: (-sum(_id_like(c) for c in t[1]), t[0], [names.index(c) for c in t[1]]),
        ):
            if verify is None or verify(cols):
                evidence.append({"columns": cols, "unique": True, "duplicate_rows": 0})
                return GrainInference(side, rows, cols, evidence, sampled=len(frame) < rows)
            evidence.append({"columns": cols, "unique": False, "note": "not unique on full data"})
    return GrainInference(side, rows, None, evidence, sampled=len(frame) < rows)


def compare_grains(left: GrainInference, right: GrainInference) -> dict[str, Any]:
    """Describe how the inferred grains relate (finer, coarser, same, unrelated)."""
    out: dict[str, Any] = {
        "left": left.to_dict(),
        "right": right.to_dict(),
        "relationship": "unknown",
        "label": "inference",
    }
    if left.columns is None or right.columns is None:
        return out
    ls, rs = set(left.columns), set(right.columns)
    if ls == rs:
        out["relationship"] = "same"
    elif rs < ls:
        out["relationship"] = "left_finer"
    elif ls < rs:
        out["relationship"] = "right_finer"
    else:
        out["relationship"] = "different"
    return out
