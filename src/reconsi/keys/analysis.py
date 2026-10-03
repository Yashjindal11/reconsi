"""Deep analysis of reconciliation keys, run before any values are compared."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from pandas.api import types as pdt

from reconsi.core.dtypes import compatible_types, logical_type
from reconsi.core.serialization import to_jsonable
from reconsi.keys.canonical import KEY_NORMALIZATIONS, SEP, combined_key, shape_of

Relationship = Literal["one-to-one", "one-to-many", "many-to-one", "many-to-many"]

MULTIPLICITY_BUCKETS: list[tuple[str, int, int]] = [
    ("1", 1, 1),
    ("2", 2, 2),
    ("3", 3, 3),
    ("4-5", 4, 5),
    ("6-10", 6, 10),
    ("11+", 11, 2**62),
]


@dataclass
class KeyFormatIssues:
    blank: int = 0
    whitespace: int = 0
    case_variants: int = 0
    leading_zeros: int = 0
    malformed: int = 0
    dominant_pattern: str | None = None
    malformed_examples: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: to_jsonable(v) for k, v in self.__dict__.items()}


@dataclass
class SideKeyProfile:
    side: str
    rows: int
    unique_keys: int
    duplicate_keys: int
    rows_in_duplicate_keys: int
    max_multiplicity: int
    mean_records_per_key: float
    multiplicity_distribution: dict[str, int]
    null_keys: int
    dtypes: dict[str, str]
    format_issues: dict[str, KeyFormatIssues]
    duplicate_examples: list[dict[str, Any]]

    @property
    def is_unique(self) -> bool:
        return self.duplicate_keys == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "rows": self.rows,
            "unique_keys": self.unique_keys,
            "is_unique": self.is_unique,
            "duplicate_keys": self.duplicate_keys,
            "rows_in_duplicate_keys": self.rows_in_duplicate_keys,
            "max_multiplicity": self.max_multiplicity,
            "mean_records_per_key": self.mean_records_per_key,
            "multiplicity_distribution": self.multiplicity_distribution,
            "null_keys": self.null_keys,
            "dtypes": self.dtypes,
            "format_issues": {k: v.to_dict() for k, v in self.format_issues.items()},
            "duplicate_examples": to_jsonable(self.duplicate_examples),
        }


@dataclass
class KeyAnalysis:
    keys: list[str]
    left: SideKeyProfile
    right: SideKeyProfile
    relationship: Relationship
    dtype_mismatches: list[dict[str, Any]]
    common_keys: int
    left_only_keys: int
    right_only_keys: int
    naive_join_rows: int
    normalization_diagnosis: list[dict[str, Any]]

    @property
    def join_inflation(self) -> int:
        """Extra rows a naive inner join on these keys would create because of duplicates."""
        return max(0, self.naive_join_rows - self.common_keys)

    def to_dict(self) -> dict[str, Any]:
        return {
            "keys": self.keys,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "relationship": self.relationship,
            "dtype_mismatches": self.dtype_mismatches,
            "common_keys": self.common_keys,
            "left_only_keys": self.left_only_keys,
            "right_only_keys": self.right_only_keys,
            "naive_join_rows": self.naive_join_rows,
            "join_inflation": self.join_inflation,
            "normalization_diagnosis": self.normalization_diagnosis,
        }


def _bucket_distribution(counts: pd.Series) -> dict[str, int]:
    dist: dict[str, int] = {}
    values = counts.to_numpy()
    for label, lo, hi in MULTIPLICITY_BUCKETS:
        n = int(((values >= lo) & (values <= hi)).sum())
        if n:
            dist[label] = n
    return dist


def _format_issues(series: pd.Series, max_distinct: int = 200_000) -> KeyFormatIssues:
    issues = KeyFormatIssues()
    if not (pdt.is_string_dtype(series.dtype) or series.dtype == object):
        return issues
    text = series.dropna()
    text = text[text.map(lambda v: isinstance(v, str))].astype(str)
    if text.empty:
        return issues
    stripped = text.str.strip()
    issues.blank = int((stripped == "").sum())
    issues.whitespace = int((text != stripped).sum())
    issues.leading_zeros = int(stripped.str.match(r"^0\d+$").sum())
    distinct = pd.Series(stripped.unique())
    if len(distinct) > max_distinct:
        distinct = distinct.sample(max_distinct, random_state=0)
    folded = distinct.str.casefold()
    issues.case_variants = int(folded.duplicated(keep=False).sum())
    shapes = distinct[distinct != ""].map(shape_of)
    if len(shapes) >= 20:
        top = shapes.value_counts()
        share = top.iloc[0] / len(shapes)
        if share >= 0.9 and len(top) > 1:
            issues.dominant_pattern = str(top.index[0])
            row_shapes = stripped.map(shape_of)
            bad = stripped[(row_shapes != issues.dominant_pattern) & (stripped != "")]
            issues.malformed = len(bad)
            issues.malformed_examples = bad.drop_duplicates().head(5).tolist()
    return issues


def profile_side(frame: pd.DataFrame, keys: list[str], side: str, ck: pd.Series) -> SideKeyProfile:
    """Profile uniqueness, nulls and formatting of ``keys`` in one dataset."""
    null_mask = frame[keys].isna().any(axis=1)
    counts = ck[~null_mask.to_numpy()].value_counts(sort=False)
    dup = counts[counts > 1]
    examples: list[dict[str, Any]] = []
    if len(dup):
        top = dup.sort_values(ascending=False, kind="stable").head(10)
        first = frame.loc[~null_mask].assign(_ck=ck[~null_mask.to_numpy()].to_numpy())
        first = first.drop_duplicates("_ck").set_index("_ck")
        for key_str, n in top.items():
            row = first.loc[key_str, keys]
            examples.append({"key": {k: row[k] for k in keys}, "count": int(n)})
    return SideKeyProfile(
        side=side,
        rows=len(frame),
        unique_keys=len(counts),
        duplicate_keys=len(dup),
        rows_in_duplicate_keys=int(dup.sum()),
        max_multiplicity=int(counts.max()) if len(counts) else 0,
        mean_records_per_key=float(counts.mean()) if len(counts) else 0.0,
        multiplicity_distribution=_bucket_distribution(counts),
        null_keys=int(null_mask.sum()),
        dtypes={k: logical_type(frame[k]) for k in keys},
        format_issues={k: _format_issues(frame[k]) for k in keys},
        duplicate_examples=examples,
    )


def _relationship(left_unique: bool, right_unique: bool) -> Relationship:
    if left_unique and right_unique:
        return "one-to-one"
    if left_unique:
        return "one-to-many"
    if right_unique:
        return "many-to-one"
    return "many-to-many"


def diagnose_normalizations(left_only: set[str], right_only: set[str]) -> list[dict[str, Any]]:
    """Count unmatched keys that *would* match if a normalisation were applied to both sides."""
    if not left_only or not right_only:
        return []
    out: list[dict[str, Any]] = []
    for name, fn in KEY_NORMALIZATIONS.items():
        right_norm = {fn(k) for k in right_only}
        hits = [k for k in left_only if fn(k) in right_norm]
        if hits:
            out.append(
                {
                    "normalization": name,
                    "would_match": len(hits),
                    "share_of_left_only": len(hits) / len(left_only),
                    "examples": [h.replace(SEP, " | ") for h in sorted(hits)[:5]],
                }
            )
    out.sort(key=lambda d: -int(d["would_match"]))
    return out


def duplicate_key_table(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Every key duplicated on either side, with its row count on each side."""
    parts = []
    for frame, side in ((left, "left"), (right, "right")):
        valid = frame.loc[~frame[keys].isna().any(axis=1), keys]
        ck = combined_key(valid, keys)
        counts = ck.value_counts()
        firsts = valid.assign(_ck=ck.to_numpy()).drop_duplicates("_ck").set_index("_ck")
        parts.append((counts, firsts, side))
    (lc, lf, _), (rc, rf, _) = parts
    dup_index = lc.index[lc > 1].union(rc.index[rc > 1])
    if len(dup_index) == 0:
        return pd.DataFrame(
            {**{k: pd.Series(dtype=object) for k in keys}, "left_count": [], "right_count": []}
        )
    firsts = pd.concat([lf, rf[~rf.index.isin(lf.index)]])
    out = firsts.loc[dup_index, keys].reset_index(drop=True)
    out["left_count"] = lc.reindex(dup_index, fill_value=0).to_numpy()
    out["right_count"] = rc.reindex(dup_index, fill_value=0).to_numpy()
    total = out["left_count"] + out["right_count"]
    order = (-total).argsort(kind="stable")
    return out.iloc[order].reset_index(drop=True)


def analyze_keys(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> KeyAnalysis:
    """Analyse ``keys`` on both datasets (which must already use the same key column names)."""
    lk, rk = combined_key(left, keys), combined_key(right, keys)
    lp = profile_side(left, keys, "left", lk)
    rp = profile_side(right, keys, "right", rk)
    dtype_mismatches = [
        {"column": k, "left": lp.dtypes[k], "right": rp.dtypes[k]}
        for k in keys
        if lp.dtypes[k] != rp.dtypes[k] and not compatible_types(lp.dtypes[k], rp.dtypes[k])
    ]
    lcounts = lk[~left[keys].isna().any(axis=1).to_numpy()].value_counts()
    rcounts = rk[~right[keys].isna().any(axis=1).to_numpy()].value_counts()
    common = lcounts.index.intersection(rcounts.index)
    left_only = set(lcounts.index.difference(rcounts.index))
    right_only = set(rcounts.index.difference(lcounts.index))
    naive = int(
        np.dot(
            lcounts.loc[common].to_numpy(dtype=np.int64),
            rcounts.loc[common].to_numpy(dtype=np.int64),
        )
    )
    return KeyAnalysis(
        keys=keys,
        left=lp,
        right=rp,
        relationship=_relationship(lp.is_unique, rp.is_unique),
        dtype_mismatches=dtype_mismatches,
        common_keys=len(common),
        left_only_keys=len(left_only),
        right_only_keys=len(right_only),
        naive_join_rows=naive,
        normalization_diagnosis=diagnose_normalizations(left_only, right_only),
    )
