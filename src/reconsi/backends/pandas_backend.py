"""In-memory pandas backend (the default)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import ClassVar, Literal

import numpy as np
import pandas as pd

from reconsi.aggregation.aggregate import aggregate_frame
from reconsi.backends.base import (
    JOIN_STATUS,
    LEFT_PREFIX,
    OCCURRENCE,
    RIGHT_PREFIX,
    Side,
    TableBackend,
)
from reconsi.comparison.values import apply_normalizations
from reconsi.core.dtypes import NUMERIC_TYPES, logical_type
from reconsi.inputs.sources import TableSource
from reconsi.keys.canonical import canonical_strings, combined_key


class PandasBackend(TableBackend):
    name: ClassVar[str] = "pandas"

    def __init__(self) -> None:
        self._tables: dict[str, pd.DataFrame] = {}

    def table(self, side: Side) -> pd.DataFrame:
        return self._tables[side]

    def load(
        self,
        side: Side,
        source: TableSource,
        *,
        rename: Mapping[str, str],
        string_columns: list[str],
    ) -> None:
        frame = source.to_pandas(string_columns=string_columns)
        frame = frame.rename(columns={c: str(c) for c in frame.columns})
        if rename:
            frame = frame.rename(columns=dict(rename))
        self._tables[side] = frame.reset_index(drop=True)

    def columns(self, side: Side) -> list[str]:
        return [str(c) for c in self._tables[side].columns]

    def row_count(self, side: Side) -> int:
        return len(self._tables[side])

    def head(self, side: Side, n: int) -> pd.DataFrame:
        return self._tables[side].head(n)

    def null_counts(self, side: Side) -> dict[str, int]:
        return {str(k): int(v) for k, v in self._tables[side].isna().sum().items()}

    def fetch(self, side: Side, columns: list[str]) -> pd.DataFrame:
        return self._tables[side][columns]

    def sample(self, side: Side, columns: list[str], n: int, seed: int) -> pd.DataFrame:
        frame = self._tables[side][columns]
        if len(frame) <= n:
            return frame
        return frame.sample(n=n, random_state=seed)

    def sums(self, side: Side, columns: list[str]) -> dict[str, float | None]:
        frame = self._tables[side]
        out: dict[str, float | None] = {}
        for c in columns:
            if c in frame.columns and logical_type(frame[c]) in NUMERIC_TYPES:
                out[c] = float(pd.to_numeric(frame[c], errors="coerce").sum())
            else:
                out[c] = None
        return out

    def aggregate(self, side: Side, keys: list[str], aggregations: Mapping[str, str]) -> None:
        self._tables[side] = aggregate_frame(self._tables[side], keys, aggregations)

    def deduplicate(self, side: Side, keys: list[str], keep: Literal["first", "last"]) -> int:
        frame = self._tables[side]
        out = frame.drop_duplicates(subset=keys, keep=keep).reset_index(drop=True)
        self._tables[side] = out
        return len(frame) - len(out)

    def remove_keys(self, side: Side, keys: list[str], key_values: pd.DataFrame) -> pd.DataFrame:
        frame = self._tables[side]
        if key_values.empty:
            return frame.iloc[0:0]
        mask = combined_key(frame, keys).isin(set(combined_key(key_values, keys))).to_numpy()
        self._tables[side] = frame.loc[~mask].reset_index(drop=True)
        return frame.loc[mask].reset_index(drop=True)

    def add_occurrence(self, side: Side, keys: list[str], order_by: list[str]) -> None:
        frame = self._tables[side]
        sort_cols = keys + [c for c in order_by if c in frame.columns]
        ordered = frame.sort_values(sort_cols, kind="stable", na_position="last")
        ordered[OCCURRENCE] = ordered.groupby(keys, dropna=False, sort=False).cumcount()
        self._tables[side] = ordered.reset_index(drop=True)

    def cast_keys_to_text(self, side: Side, keys: list[str]) -> None:
        frame = self._tables[side].copy()
        for k in keys:
            frame[k] = canonical_strings(frame[k])
        self._tables[side] = frame

    def normalize_keys(self, side: Side, keys: list[str], steps: list[str]) -> None:
        frame = self._tables[side].copy()
        for k in keys:
            text = canonical_strings(frame[k])
            mask = text.isna()
            normalized = apply_normalizations(text.fillna("").astype(object), steps).astype(object)
            normalized[mask.to_numpy()] = None
            frame[k] = normalized
        self._tables[side] = frame

    def join(
        self,
        keys: list[str],
        left_columns: list[str],
        right_columns: list[str],
        chunk_size: int,
    ) -> Iterator[pd.DataFrame]:
        left = self._tables["left"][keys + left_columns].rename(
            columns={c: LEFT_PREFIX + c for c in left_columns}
        )
        right = self._tables["right"][keys + right_columns].rename(
            columns={c: RIGHT_PREFIX + c for c in right_columns}
        )
        lnull = left[keys].isna().any(axis=1).to_numpy()
        rnull = right[keys].isna().any(axis=1).to_numpy()
        merged = left.loc[~lnull].merge(
            right.loc[~rnull], on=keys, how="outer", indicator=JOIN_STATUS, sort=False
        )
        merged[JOIN_STATUS] = merged[JOIN_STATUS].astype(str)
        parts = [merged]
        if lnull.any():
            parts.append(left.loc[lnull].assign(**{JOIN_STATUS: "left_only"}))
        if rnull.any():
            parts.append(right.loc[rnull].assign(**{JOIN_STATUS: "right_only"}))
        if len(parts) > 1:
            merged = pd.concat(parts, ignore_index=True)
        merged = merged.reset_index(drop=True)
        n = len(merged)
        if n == 0:
            yield merged
            return
        for start in np.arange(0, n, chunk_size):
            yield merged.iloc[int(start) : int(start) + chunk_size]
