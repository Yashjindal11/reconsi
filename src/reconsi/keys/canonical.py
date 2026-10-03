"""Canonical string forms of key values, used to compare keys across differing dtypes."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

import numpy as np
import pandas as pd

from reconsi.core.dtypes import logical_type

SEP = "\x1f"
NULL_TOKEN = "\x00null"  # noqa: S105 - sentinel, not a credential


def canonical_strings(series: pd.Series) -> pd.Series:
    """Render values as strings such that ``1``, ``1.0`` and ``"1"`` all become ``"1"``.

    Nulls are returned as ``None``. The result has object dtype.
    """
    ltype = logical_type(series)
    mask = series.isna().to_numpy()
    if ltype == "integer":
        out = series.astype("Int64").astype(str)
    elif ltype == "float":
        values = series.to_numpy(dtype=float, na_value=np.nan)
        finite = values[~mask]
        if len(finite) and np.all(np.mod(finite, 1) == 0) and np.all(np.abs(finite) < 2**53):
            out = series.astype("Int64").astype(str)
        else:
            out = pd.Series([repr(float(v)) for v in values], index=series.index)
    elif ltype in {"datetime", "datetime_tz"}:
        stamps = [None if m else pd.Timestamp(v) for v, m in zip(series, mask, strict=True)]
        # Date-only values render as YYYY-MM-DD so they match text dates from CSV files.
        date_only = all(s is None or (s == s.normalize() and s.tzinfo is None) for s in stamps)
        out = pd.Series(
            [
                None if s is None else (s.strftime("%Y-%m-%d") if date_only else s.isoformat())
                for s in stamps
            ],
            index=series.index,
        )
    elif ltype == "date":
        out = series.map(lambda v: None if v is None or v != v else v.isoformat())
    else:
        out = series.astype(str)
    result = out.astype(object)
    result[mask] = None
    return result


def combined_key(frame: pd.DataFrame, keys: list[str]) -> pd.Series:
    """Join canonical key components into a single string per row (nulls get a sentinel)."""
    parts = [canonical_strings(frame[k]).fillna(NULL_TOKEN).astype(object) for k in keys]
    combined = parts[0].astype(str)
    for p in parts[1:]:
        combined = combined + SEP + p.astype(str)
    return combined.astype(object)


def _per_component(fn: Callable[[str], str]) -> Callable[[str], str]:
    def apply(value: str) -> str:
        return SEP.join(p if p == NULL_TOKEN else fn(p) for p in value.split(SEP))

    return apply


def _strip_leading_zeros(text: str) -> str:
    return re.sub(r"^0+(?=\d)", "", text.strip())


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", text).casefold())


KEY_NORMALIZATIONS: dict[str, Callable[[str], str]] = {
    "trim": _per_component(str.strip),
    "casefold": _per_component(str.casefold),
    "collapse_whitespace": _per_component(_collapse),
    "strip_leading_zeros": _per_component(_strip_leading_zeros),
    "unicode_nfkc": _per_component(lambda s: unicodedata.normalize("NFKC", s)),
    "alphanumeric_only": _per_component(_alnum),
}


def shape_of(text: str) -> str:
    """Collapse a value into a character-class pattern: ``CUST-00123`` -> ``A-9``."""
    shape = re.sub(r"[0-9]+", "9", text)
    shape = re.sub(r"[A-Za-z]+", "A", shape)
    return re.sub(r"\s+", "_", shape)
