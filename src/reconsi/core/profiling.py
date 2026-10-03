"""Choose analysis dimensions and the date column from a sample of the data."""

from __future__ import annotations

import re

import pandas as pd

from reconsi.core.dtypes import TEMPORAL_TYPES, logical_type

DATE_NAME = re.compile(r"(^|_)(date|day|dt|period|month|week)($|_)", re.IGNORECASE)


def detect_dimensions(
    frames: list[pd.DataFrame],
    candidates: list[str],
    *,
    exclude: set[str],
    max_dimensions: int,
    max_levels: int,
) -> list[str]:
    """Low-cardinality categorical columns suitable for mismatch-concentration analysis."""
    out: list[str] = []
    for col in candidates:
        if col in exclude or len(out) >= max_dimensions:
            continue
        series = [f[col] for f in frames if col in f.columns]
        if not series:
            continue
        ltype = logical_type(series[0])
        if ltype not in {"string", "categorical", "boolean", "integer"}:
            continue
        values = pd.concat([s.dropna() for s in series], ignore_index=True)
        if values.empty:
            continue
        n_levels = values.nunique()
        if n_levels < 2 or n_levels > max_levels:
            continue
        # Integers are only treated as categories when they repeat a lot (codes, not amounts).
        if ltype == "integer" and n_levels > max(10, len(values) // 20):
            continue
        out.append(col)
    return out


def detect_date_column(frames: list[pd.DataFrame], candidates: list[str]) -> str | None:
    """First datetime-typed column, else a date-named text column that parses as dates."""
    for col in candidates:
        for f in frames:
            if col in f.columns and logical_type(f[col]) in TEMPORAL_TYPES:
                return col
    for col in candidates:
        if not DATE_NAME.search(col):
            continue
        for f in frames:
            if col not in f.columns or logical_type(f[col]) != "string":
                continue
            values = f[col].dropna().head(500)
            if values.empty:
                continue
            parsed = pd.to_datetime(values, errors="coerce", format="mixed")
            if parsed.notna().mean() >= 0.95:
                return col
    return None


def to_period(values: pd.Series, frequency: str) -> pd.Series:
    """Parse ``values`` as dates and bucket them into day / week / month periods."""
    if isinstance(values.dtype, pd.DatetimeTZDtype):
        parsed = values.dt.tz_convert("UTC").dt.tz_localize(None)
    elif pd.api.types.is_datetime64_dtype(values.dtype):
        parsed = values
    else:
        parsed = pd.to_datetime(values, errors="coerce", format="mixed", utc=True)
        parsed = parsed.dt.tz_localize(None)
    if frequency == "D":
        return parsed.dt.floor("D")
    return parsed.dt.to_period(frequency).dt.start_time
