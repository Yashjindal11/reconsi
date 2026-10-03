"""Stream joined chunks through the column comparators and accumulate record-level results."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from reconsi.backends.base import JOIN_STATUS, LEFT_PREFIX, RIGHT_PREFIX
from reconsi.comparison.options import ColumnOptions
from reconsi.comparison.values import compare_column, constant_offset_hint
from reconsi.core.serialization import json_dict
from reconsi.core.types import RecordStatus
from reconsi.statistics.intervals import describe_differences, wilson_interval

STATUS = "_status"
MISMATCHED_COLUMNS = "_mismatched_columns"
DATE = "_date"
DIM_PREFIX = "dim."


@dataclass
class ColumnStatistics:
    column: str
    kind: str
    left_dtype: str
    right_dtype: str
    compared: int = 0
    matches: int = 0
    mismatches: int = 0
    within_tolerance: int = 0
    both_null: int = 0
    mismatch_types: Counter[str] = field(default_factory=Counter)
    datatype_mismatch: bool = False
    effective: dict[str, Any] = field(default_factory=dict)
    hints: list[dict[str, Any]] = field(default_factory=list)
    critical: bool = False
    differences: dict[str, Any] | None = None
    mismatch_differences: dict[str, Any] | None = None
    relative_differences: dict[str, Any] | None = None
    totals: dict[str, float | None] | None = None
    histogram: dict[str, list[float]] | None = None

    @property
    def match_rate(self) -> float:
        return self.matches / self.compared if self.compared else 1.0

    @property
    def mismatch_rate(self) -> float:
        return self.mismatches / self.compared if self.compared else 0.0

    @property
    def classification(self) -> str:
        if self.mismatches == 0:
            return "match_within_tolerance" if self.within_tolerance else "exact_match"
        dominant = self.mismatch_types.most_common(1)[0][0]
        return f"{dominant}_mismatch"

    def to_dict(self) -> dict[str, Any]:
        lo, hi = wilson_interval(self.mismatches, self.compared)
        return json_dict(
            {
                "column": self.column,
                "kind": self.kind,
                "classification": self.classification,
                "left_dtype": self.left_dtype,
                "right_dtype": self.right_dtype,
                "datatype_mismatch": self.datatype_mismatch,
                "critical": self.critical,
                "compared": self.compared,
                "matches": self.matches,
                "mismatches": self.mismatches,
                "match_percentage": 100 * self.match_rate,
                "mismatch_percentage": 100 * self.mismatch_rate,
                "mismatch_percentage_ci95": [100 * lo, 100 * hi],
                "within_tolerance": self.within_tolerance,
                "both_null": self.both_null,
                "null_mismatches": self.mismatch_types.get("null", 0),
                "mismatch_types": dict(self.mismatch_types),
                "comparison": self.effective,
                "differences": self.differences,
                "mismatch_differences": self.mismatch_differences,
                "relative_differences": self.relative_differences,
                "totals": self.totals,
                "mismatch_histogram": self.histogram,
                "hints": self.hints,
            }
        )


def difference_histogram(values: np.ndarray, bins: int = 30) -> dict[str, list[float]] | None:
    """Histogram of finite differences (for charts)."""
    v = values[np.isfinite(values)]
    if len(v) == 0:
        return None
    try:
        counts, edges = np.histogram(v, bins=bins)
    except ValueError:  # range too narrow for float bins
        counts, edges = np.array([len(v)]), np.array([v.min(), v.max()])
    return {"counts": [float(c) for c in counts], "edges": [float(e) for e in edges]}


def _merge_hints(acc: list[dict[str, Any]], new: list[dict[str, Any]]) -> None:
    for hint in new:
        ident = (hint["kind"], hint.get("normalization"), hint.get("precision"))
        for existing in acc:
            if (
                existing["kind"],
                existing.get("normalization"),
                existing.get("precision"),
            ) == ident:
                for k in ("would_resolve", "of_mismatches"):
                    if k in hint:
                        existing[k] = existing.get(k, 0) + hint[k]
                break
        else:
            acc.append(dict(hint))


@dataclass
class RecordAccumulator:
    keys: list[str]
    compare_columns: list[str]
    options: dict[str, ColumnOptions]
    kinds: dict[str, str]
    dtypes: dict[str, tuple[str, str]]
    dtype_mismatch: dict[str, bool]
    dimensions: list[str]
    date_column: str | None
    left_columns: list[str]
    right_columns: list[str]
    max_detail_rows: int

    columns: dict[str, ColumnStatistics] = field(init=False)
    _records: list[pd.DataFrame] = field(default_factory=list, init=False)
    _mismatches: list[pd.DataFrame] = field(default_factory=list, init=False)
    _missing_left: list[pd.DataFrame] = field(default_factory=list, init=False)
    _missing_right: list[pd.DataFrame] = field(default_factory=list, init=False)
    _diffs: dict[str, list[np.ndarray]] = field(default_factory=dict, init=False)
    _rel: dict[str, list[np.ndarray]] = field(default_factory=dict, init=False)
    _mismatch_diffs: dict[str, list[np.ndarray]] = field(default_factory=dict, init=False)
    _sums: dict[str, list[float]] = field(default_factory=dict, init=False)
    mismatch_rows_total: int = field(default=0, init=False)
    missing_left_total: int = field(default=0, init=False)
    missing_right_total: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.columns = {
            c: ColumnStatistics(
                column=c,
                kind=self.kinds[c],
                left_dtype=self.dtypes[c][0],
                right_dtype=self.dtypes[c][1],
                datatype_mismatch=self.dtype_mismatch[c],
                critical=self.options[c].critical,
            )
            for c in self.compare_columns
        }
        for c in self.compare_columns:
            self._diffs[c], self._rel[c], self._mismatch_diffs[c] = [], [], []
            self._sums[c] = [0.0, 0.0]

    def _side_value(self, chunk: pd.DataFrame, column: str) -> pd.Series:
        if column in self.keys:
            return chunk[column]
        lc, rc = LEFT_PREFIX + column, RIGHT_PREFIX + column
        if lc in chunk.columns and rc in chunk.columns:
            left = chunk[lc]
            return left.where(left.notna(), chunk[rc])
        return chunk[lc] if lc in chunk.columns else chunk[rc]

    def add(self, chunk: pd.DataFrame) -> None:
        side = chunk[JOIN_STATUS].to_numpy()
        both = side == "both"
        pairs = chunk.loc[both]
        n_mismatched = np.zeros(len(pairs), dtype=np.int32)
        for col in self.compare_columns:
            n_mismatched += self._compare(col, pairs)
        status = np.full(len(chunk), RecordStatus.MATCHED.value, dtype=object)
        status[side == "left_only"] = RecordStatus.MISSING_RIGHT.value
        status[side == "right_only"] = RecordStatus.MISSING_LEFT.value
        both_status = np.where(
            n_mismatched > 0, RecordStatus.VALUE_MISMATCH.value, RecordStatus.MATCHED.value
        )
        status[both] = both_status
        mism = np.zeros(len(chunk), dtype=np.int32)
        mism[both] = n_mismatched
        records = chunk[self.keys].copy()
        records[STATUS] = status
        records[MISMATCHED_COLUMNS] = mism
        # Assign Series (same index) rather than numpy arrays: avoids re-inferring string dtypes.
        for d in self.dimensions:
            records[DIM_PREFIX + d] = self._side_value(chunk, d)
        if self.date_column is not None:
            records[DATE] = self._side_value(chunk, self.date_column)
        self._records.append(records)
        self._collect_missing(chunk, side)

    def _collect_missing(self, chunk: pd.DataFrame, side: np.ndarray) -> None:
        for flag, cols, prefix, store, attr in (
            (
                "left_only",
                self.left_columns,
                LEFT_PREFIX,
                self._missing_right,
                "missing_right_total",
            ),
            (
                "right_only",
                self.right_columns,
                RIGHT_PREFIX,
                self._missing_left,
                "missing_left_total",
            ),
        ):
            rows = chunk.loc[side == flag]
            if rows.empty:
                continue
            total = getattr(self, attr)
            setattr(self, attr, total + len(rows))
            room = self.max_detail_rows - total
            if room <= 0:
                continue
            rows = rows.head(room)
            out = rows[self.keys + [prefix + c for c in cols]]
            store.append(out.rename(columns={prefix + c: c for c in cols}))

    def _compare(self, col: str, pairs: pd.DataFrame) -> np.ndarray:
        stats = self.columns[col]
        opts = self.options[col].model_copy(update={"type": self.kinds[col]})
        left = pairs[LEFT_PREFIX + col]
        right = pairs[RIGHT_PREFIX + col]
        cc = compare_column(col, left, right, opts)
        mismatched = ~cc.equal
        stats.compared += len(cc.equal)
        stats.matches += int(cc.equal.sum())
        stats.mismatches += int(mismatched.sum())
        stats.within_tolerance += int(cc.within_tolerance.sum())
        stats.both_null += int((left.isna().to_numpy() & right.isna().to_numpy()).sum())
        stats.mismatch_types.update(t for t in cc.mismatch_type[mismatched].tolist())
        stats.effective = cc.effective
        _merge_hints(stats.hints, [h for h in cc.hints if h["kind"] != "constant_offset"])
        if cc.difference is not None:
            self._diffs[col].append(cc.difference)
            self._mismatch_diffs[col].append(cc.difference[mismatched])
            if cc.relative_difference is not None:
                self._rel[col].append(cc.relative_difference)
            if cc.kind == "numeric":
                lnum = pd.to_numeric(left, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
                rnum = pd.to_numeric(right, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
                both = np.isfinite(lnum) & np.isfinite(rnum)
                self._sums[col][0] += float(lnum[both].sum())
                self._sums[col][1] += float(rnum[both].sum())
        if mismatched.any():
            self._add_mismatch_rows(col, pairs, cc, mismatched)
        return mismatched.astype(np.int32)

    def _add_mismatch_rows(
        self, col: str, pairs: pd.DataFrame, cc: Any, mismatched: np.ndarray
    ) -> None:
        count = int(mismatched.sum())
        room = self.max_detail_rows - self.mismatch_rows_total
        self.mismatch_rows_total += count
        if room <= 0:
            return
        idx = np.flatnonzero(mismatched)[:room]
        rows = pairs[self.keys].iloc[idx].reset_index(drop=True)
        rows["column"] = col
        rows["left_value"] = pairs[LEFT_PREFIX + col].iloc[idx].astype(object).to_numpy()
        rows["right_value"] = pairs[RIGHT_PREFIX + col].iloc[idx].astype(object).to_numpy()
        diff = cc.difference[idx] if cc.difference is not None else np.full(len(idx), np.nan)
        rel = (
            cc.relative_difference[idx]
            if cc.relative_difference is not None
            else np.full(len(idx), np.nan)
        )
        rows["difference"] = diff
        rows["relative_difference"] = rel
        rows["mismatch_type"] = cc.mismatch_type[idx]
        self._mismatches.append(rows)

    def finalize(self) -> None:
        for col, stats in self.columns.items():
            if self._diffs[col]:
                diffs = np.concatenate(self._diffs[col])
                stats.differences = describe_differences(diffs)
                mdiffs = np.concatenate(self._mismatch_diffs[col])
                stats.mismatch_differences = describe_differences(mdiffs)
                stats.histogram = difference_histogram(mdiffs)
                if self._rel[col]:
                    stats.relative_differences = describe_differences(
                        np.concatenate(self._rel[col])
                    )
                if stats.kind == "datetime":
                    hint = constant_offset_hint(mdiffs)
                    if hint:
                        stats.hints.insert(0, hint)
                if stats.kind == "numeric":
                    ls, rs = self._sums[col]
                    stats.totals = {
                        "left_sum": ls,
                        "right_sum": rs,
                        "difference": rs - ls,
                        "relative_difference": (rs - ls) / abs(ls) if ls else None,
                    }

    def all_differences(self, col: str) -> np.ndarray:
        parts = self._diffs.get(col) or []
        return np.concatenate(parts) if parts else np.array([], dtype=float)

    def all_relative_differences(self, col: str) -> np.ndarray:
        parts = self._rel.get(col) or []
        return np.concatenate(parts) if parts else np.array([], dtype=float)

    def _sorted(self, frame: pd.DataFrame, extra: list[str] | None = None) -> pd.DataFrame:
        """Deterministic order regardless of backend/join order."""
        by = [*self.keys, *(extra or [])]
        try:
            return frame.sort_values(by, kind="stable", na_position="last").reset_index(drop=True)
        except TypeError:  # incomparable mixed-type keys: keep encounter order
            return frame

    def records(self) -> pd.DataFrame:
        if not self._records:
            return pd.DataFrame()
        return self._sorted(pd.concat(self._records, ignore_index=True))

    def mismatches(self) -> pd.DataFrame:
        if not self._mismatches:
            cols = [
                *self.keys,
                "column",
                "left_value",
                "right_value",
                "difference",
                "relative_difference",
                "mismatch_type",
            ]
            return pd.DataFrame({c: pd.Series(dtype=object) for c in cols})
        frame = pd.concat(self._mismatches, ignore_index=True)
        order = {c: i for i, c in enumerate(self.compare_columns)}
        frame["_col_order"] = frame["column"].map(order)
        frame = self._sorted(frame, ["_col_order"]).drop(columns="_col_order")
        self._mismatches = [frame]
        return frame

    def missing(self, which: str) -> pd.DataFrame:
        parts = self._missing_left if which == "left" else self._missing_right
        cols = self.right_columns if which == "left" else self.left_columns
        if not parts:
            return pd.DataFrame({c: pd.Series(dtype=object) for c in self.keys + cols})
        return self._sorted(pd.concat(parts, ignore_index=True))
