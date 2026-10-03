"""Aggregation helpers shared by grain reconciliation and duplicate-aware strategies."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from reconsi.core.dtypes import NUMERIC_TYPES, logical_type
from reconsi.core.errors import ConfigurationError

SIZE_AGGREGATIONS = frozenset({"size"})


def default_aggregations(frame: pd.DataFrame, columns: list[str]) -> dict[str, str]:
    """Sum numeric columns; other columns are not aggregated (and therefore not compared)."""
    return {c: "sum" for c in columns if logical_type(frame[c]) in NUMERIC_TYPES}


def validate_aggregations(columns: list[str], aggregations: Mapping[str, str]) -> None:
    for col, fn in aggregations.items():
        if fn in SIZE_AGGREGATIONS or (fn == "count" and col not in columns):
            continue
        if col not in columns:
            raise ConfigurationError(
                f"aggregation column {col!r} not found; available columns: {columns}"
            )


def aggregate_frame(
    frame: pd.DataFrame, keys: list[str], aggregations: Mapping[str, str]
) -> pd.DataFrame:
    """Group ``frame`` by ``keys`` and apply ``aggregations``.

    ``count`` on a column that does not exist (or ``size``) counts rows per group, which is how a
    transaction table is reconciled against a summary's ``orders`` column.
    """
    validate_aggregations([str(c) for c in frame.columns], aggregations)
    named: dict[str, tuple[str, str]] = {}
    for col, fn in aggregations.items():
        if fn in SIZE_AGGREGATIONS or (fn == "count" and col not in frame.columns):
            named[col] = (keys[0], "size")
        else:
            named[col] = (col, fn)
    grouped = frame.groupby(keys, dropna=False, sort=True)
    out = grouped.agg(**named).reset_index()
    return out
