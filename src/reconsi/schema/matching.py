"""Suggest likely column correspondences between two datasets, without any language model.

Signals: normalised and abbreviation-expanded names, token overlap, logical type compatibility,
uniqueness similarity, and overlap of observed values. Suggestions are never applied
automatically; they are surfaced to the user who may add them to ``column_mapping``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import pandas as pd

from reconsi.core.dtypes import compatible_types, logical_type

ABBREVIATIONS: dict[str, str] = {
    "acct": "account",
    "addr": "address",
    "amt": "amount",
    "avg": "average",
    "bal": "balance",
    "cat": "category",
    "cnt": "count",
    "cust": "customer",
    "ctry": "country",
    "curr": "currency",
    "desc": "description",
    "dept": "department",
    "dt": "date",
    "emp": "employee",
    "inv": "invoice",
    "loc": "location",
    "mgr": "manager",
    "no": "number",
    "num": "number",
    "nbr": "number",
    "ord": "order",
    "pct": "percent",
    "prod": "product",
    "qty": "quantity",
    "rev": "revenue",
    "sku": "product",
    "st": "status",
    "tot": "total",
    "ts": "timestamp",
    "txn": "transaction",
    "trx": "transaction",
    "trans": "transaction",
    "upd": "updated",
    "val": "value",
}

_SPLIT = re.compile(r"[^0-9a-zA-Z]+|(?<=[a-z])(?=[A-Z])")


def name_tokens(name: str) -> list[str]:
    """Split ``custID`` / ``cust_id`` / ``Cust-Id`` into expanded lowercase tokens."""
    raw = [t.lower() for t in _SPLIT.split(name) if t]
    return [ABBREVIATIONS.get(t, t) for t in raw]


def normalized_name(name: str) -> str:
    return "_".join(name_tokens(name))


def name_similarity(a: str, b: str) -> float:
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    seq = SequenceMatcher(None, "".join(ta), "".join(tb)).ratio()
    jaccard = len(set(ta) & set(tb)) / len(set(ta) | set(tb))
    return max(seq, jaccard)


@dataclass(frozen=True)
class ColumnMatchSuggestion:
    left: str
    right: str
    score: float
    signals: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left,
            "right": self.right,
            "score": round(self.score, 3),
            "signals": {k: round(v, 3) for k, v in self.signals.items()},
            "label": "suggestion",
        }


def _value_overlap(a: pd.Series, b: pd.Series, sample: int) -> float | None:
    va = a.dropna().astype(str).head(sample).unique()
    vb = b.dropna().astype(str).head(sample).unique()
    if len(va) == 0 or len(vb) == 0:
        return None
    sa, sb = set(va.tolist()), set(vb.tolist())
    return len(sa & sb) / min(len(sa), len(sb))


def _uniqueness(s: pd.Series) -> float:
    non_null = s.dropna()
    return float(non_null.nunique() / len(non_null)) if len(non_null) else 0.0


def suggest_column_matches(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_columns: list[str] | None = None,
    right_columns: list[str] | None = None,
    *,
    min_score: float = 0.55,
    sample: int = 5000,
) -> list[ColumnMatchSuggestion]:
    """Rank plausible ``left -> right`` column pairs among the given (typically unmatched) columns.

    Each left and right column appears in at most one suggestion (greedy by score).
    """
    lcols = left_columns if left_columns is not None else [str(c) for c in left.columns]
    rcols = right_columns if right_columns is not None else [str(c) for c in right.columns]
    lsample, rsample = left.head(sample), right.head(sample)
    candidates: list[ColumnMatchSuggestion] = []
    for lc in lcols:
        lt = logical_type(lsample[lc])
        for rc in rcols:
            rt = logical_type(rsample[rc])
            signals: dict[str, float] = {"name": name_similarity(lc, rc)}
            signals["type"] = 1.0 if compatible_types(lt, rt) else 0.0
            signals["uniqueness"] = 1.0 - abs(_uniqueness(lsample[lc]) - _uniqueness(rsample[rc]))
            overlap = _value_overlap(lsample[lc], rsample[rc], sample)
            weights = {"name": 0.55, "type": 0.2, "uniqueness": 0.1}
            if overlap is not None:
                signals["value_overlap"] = overlap
                weights["value_overlap"] = 0.25
            score = sum(signals[k] * w for k, w in weights.items()) / sum(weights.values())
            if signals["type"] == 0.0:
                score *= 0.6
            if score >= min_score:
                candidates.append(ColumnMatchSuggestion(lc, rc, score, signals))
    candidates.sort(key=lambda s: (-s.score, s.left, s.right))
    used_l: set[str] = set()
    used_r: set[str] = set()
    chosen: list[ColumnMatchSuggestion] = []
    for cand in candidates:
        if cand.left in used_l or cand.right in used_r:
            continue
        used_l.add(cand.left)
        used_r.add(cand.right)
        chosen.append(cand)
    return chosen
