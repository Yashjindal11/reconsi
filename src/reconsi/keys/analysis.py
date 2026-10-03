"""Deep analysis of reconciliation keys, run before any values are compared."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from pandas.api import types as pdt

from reconsi.core.dtypes import compatible_types, logical_type
from reconsi.core.serialization import to_jsonable
from reconsi.keys.canonical import (
    KEY_NORMALIZATIONS,
    SEP,
    canonical_strings,
    combined_key,
    shape_of,
)

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


def key_codes(frames: list[pd.DataFrame], keys: list[str]) -> tuple[list[np.ndarray], int]:
    """Factorise key values jointly across ``frames``: equal keys get equal integer codes.

    Rows with a null key component get ``-1``. When a key column's logical type differs between
    frames, values are compared through their canonical text form (``1`` == ``"1"``).
    """
    sizes = [len(f) for f in frames]
    columns = []
    for k in keys:
        types = {logical_type(f[k]) for f in frames} - {"empty"}
        parts = [f[k] for f in frames]
        if len(types) > 1 or types & {"mixed", "datetime_tz"}:
            parts = [canonical_strings(p) for p in parts]
        joined = pd.concat([p.reset_index(drop=True) for p in parts], ignore_index=True)
        codes, _ = pd.factorize(joined, use_na_sentinel=True)
        columns.append(codes.astype(np.int64))
    if len(columns) == 1:
        combined = columns[0]
    else:
        stacked = np.vstack(columns)
        null = (stacked < 0).any(axis=0)
        combined = np.full(stacked.shape[1], -1, dtype=np.int64)
        if (~null).any():
            ids, _ = pd.factorize(pd.MultiIndex.from_arrays(list(stacked[:, ~null])))
            combined[~null] = ids
    n = int(np.max(combined)) + 1 if len(combined) else 0
    out, start = [], 0
    for size in sizes:
        out.append(combined[start : start + size])
        start += size
    return out, n


def _first_rows(codes: np.ndarray, n: int) -> np.ndarray:
    """Row position of the first occurrence of each code (``-1`` when absent)."""
    first = np.full(n, -1, dtype=np.int64)
    valid = np.flatnonzero(codes >= 0)
    uniq, idx = np.unique(codes[valid], return_index=True)
    first[uniq] = valid[idx]
    return first


def _profile(
    frame: pd.DataFrame, keys: list[str], side: str, codes: np.ndarray, n: int
) -> tuple[SideKeyProfile, np.ndarray]:
    counts_all = np.bincount(codes[codes >= 0], minlength=n)
    present = counts_all[counts_all > 0]
    dup_codes = np.flatnonzero(counts_all > 1)
    examples: list[dict[str, Any]] = []
    if len(dup_codes):
        top = dup_codes[np.argsort(-counts_all[dup_codes], kind="stable")][:10]
        first = _first_rows(codes, n)
        for code in top:
            row = frame.iloc[int(first[code])]
            examples.append({"key": {k: row[k] for k in keys}, "count": int(counts_all[code])})
    profile = SideKeyProfile(
        side=side,
        rows=len(frame),
        unique_keys=len(present),
        duplicate_keys=len(dup_codes),
        rows_in_duplicate_keys=int(counts_all[dup_codes].sum()),
        max_multiplicity=int(np.max(present)) if len(present) else 0,
        mean_records_per_key=float(np.mean(present)) if len(present) else 0.0,
        multiplicity_distribution=_bucket_distribution(pd.Series(present)),
        null_keys=int((codes < 0).sum()),
        dtypes={k: logical_type(frame[k]) for k in keys},
        format_issues={k: _format_issues(frame[k]) for k in keys},
        duplicate_examples=examples,
    )
    return profile, counts_all


def profile_keys(frame: pd.DataFrame, keys: list[str], side: str = "dataset") -> SideKeyProfile:
    """Uniqueness, nulls and formatting of ``keys`` in a single dataset."""
    (codes,), n = key_codes([frame], keys)
    return _profile(frame, keys, side, codes, n)[0]


def _relationship(left_unique: bool, right_unique: bool) -> Relationship:
    if left_unique and right_unique:
        return "one-to-one"
    if left_unique:
        return "one-to-many"
    if right_unique:
        return "many-to-one"
    return "many-to-many"


def diagnose_normalizations(
    left_only: set[str], right_only: set[str], max_keys: int = 200_000
) -> list[dict[str, Any]]:
    """Count unmatched keys that *would* match if a normalisation were applied to both sides."""
    if not left_only or not right_only:
        return []
    sampled = len(left_only) > max_keys or len(right_only) > max_keys
    lo = sorted(left_only)[:max_keys] if sampled else left_only
    ro = sorted(right_only)[:max_keys] if sampled else right_only
    out: list[dict[str, Any]] = []
    for name, fn in KEY_NORMALIZATIONS.items():
        right_norm = {fn(k) for k in ro}
        hits = [k for k in lo if fn(k) in right_norm]
        if hits:
            out.append(
                {
                    "normalization": name,
                    "would_match": len(hits),
                    "share_of_left_only": len(hits) / len(lo),
                    "examples": [h.replace(SEP, " | ") for h in sorted(hits)[:5]],
                    "sampled": sampled,
                }
            )
    out.sort(key=lambda d: -int(d["would_match"]))
    return out


def _key_strings(frame: pd.DataFrame, keys: list[str], rows: np.ndarray) -> set[str]:
    if len(rows) == 0:
        return set()
    return set(combined_key(frame.iloc[rows].reset_index(drop=True), keys))


def analyze_keys_with_duplicates(
    left: pd.DataFrame, right: pd.DataFrame, keys: list[str]
) -> tuple[KeyAnalysis, pd.DataFrame]:
    """Key analysis plus the table of every key duplicated on either side."""
    (lcodes, rcodes), n = key_codes([left, right], keys)
    lp, lc = _profile(left, keys, "left", lcodes, n)
    rp, rc = _profile(right, keys, "right", rcodes, n)
    dtype_mismatches = [
        {"column": k, "left": lp.dtypes[k], "right": rp.dtypes[k]}
        for k in keys
        if lp.dtypes[k] != rp.dtypes[k] and not compatible_types(lp.dtypes[k], rp.dtypes[k])
    ]
    common = (lc > 0) & (rc > 0)
    left_only = np.flatnonzero((lc > 0) & (rc == 0))
    right_only = np.flatnonzero((rc > 0) & (lc == 0))
    lfirst, rfirst = _first_rows(lcodes, n), _first_rows(rcodes, n)
    diagnosis = []
    if len(left_only) and len(right_only):
        diagnosis = diagnose_normalizations(
            _key_strings(left, keys, lfirst[left_only]),
            _key_strings(right, keys, rfirst[right_only]),
        )
    analysis = KeyAnalysis(
        keys=keys,
        left=lp,
        right=rp,
        relationship=_relationship(lp.is_unique, rp.is_unique),
        dtype_mismatches=dtype_mismatches,
        common_keys=int(common.sum()),
        left_only_keys=len(left_only),
        right_only_keys=len(right_only),
        naive_join_rows=int(np.dot(lc.astype(np.int64), rc.astype(np.int64))),
        normalization_diagnosis=diagnosis,
    )
    dup = np.flatnonzero((lc > 1) | (rc > 1))
    if len(dup) == 0:
        table = pd.DataFrame(
            {**{k: pd.Series(dtype=object) for k in keys}, "left_count": [], "right_count": []}
        )
        return analysis, table
    from_left = lfirst[dup] >= 0
    lrows = left.iloc[lfirst[dup][from_left]][keys].reset_index(drop=True)
    rrows = right.iloc[rfirst[dup][~from_left]][keys].reset_index(drop=True)
    table = pd.concat([lrows, rrows], ignore_index=True)
    ordered = np.concatenate([dup[from_left], dup[~from_left]])
    table["left_count"] = lc[ordered]
    table["right_count"] = rc[ordered]
    order = np.argsort(-(table["left_count"] + table["right_count"]).to_numpy(), kind="stable")
    return analysis, table.iloc[order].reset_index(drop=True)


def duplicate_key_table(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Every key duplicated on either side, with its row count on each side."""
    return analyze_keys_with_duplicates(left, right, keys)[1]


def analyze_keys(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> KeyAnalysis:
    """Analyse ``keys`` on both datasets (which must already use the same key column names)."""
    return analyze_keys_with_duplicates(left, right, keys)[0]
