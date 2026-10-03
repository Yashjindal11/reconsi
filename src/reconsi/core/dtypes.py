"""Logical type detection that is stable across pandas 2.x and 3.x."""

from __future__ import annotations

from typing import Literal

import pandas as pd
from pandas.api import types as pdt

LogicalType = Literal[
    "integer",
    "float",
    "boolean",
    "datetime",
    "datetime_tz",
    "date",
    "timedelta",
    "string",
    "categorical",
    "mixed",
    "empty",
]

NUMERIC_TYPES: frozenset[str] = frozenset({"integer", "float"})
TEMPORAL_TYPES: frozenset[str] = frozenset({"datetime", "datetime_tz", "date"})
TEXT_TYPES: frozenset[str] = frozenset({"string", "categorical"})


def logical_type(series: pd.Series) -> LogicalType:
    """Classify a column into a small set of logical types used for comparison."""
    dtype = series.dtype
    if pdt.is_bool_dtype(dtype):
        return "boolean"
    if pdt.is_integer_dtype(dtype):
        return "integer"
    if pdt.is_float_dtype(dtype):
        return "float"
    if isinstance(dtype, pd.DatetimeTZDtype):
        return "datetime_tz"
    if pdt.is_datetime64_dtype(dtype):
        return "datetime"
    if pdt.is_timedelta64_dtype(dtype):
        return "timedelta"
    if isinstance(dtype, pd.CategoricalDtype):
        return "categorical"
    inferred = pdt.infer_dtype(series, skipna=True)
    mapping: dict[str, LogicalType] = {
        "string": "string",
        "empty": "empty",
        "integer": "integer",
        "floating": "float",
        "mixed-integer-float": "float",
        "decimal": "float",
        "boolean": "boolean",
        "date": "date",
        "datetime": "datetime",
        "datetime64": "datetime",
        "timedelta": "timedelta",
        "timedelta64": "timedelta",
    }
    if inferred in mapping:
        if mapping[inferred] == "datetime":
            non_null = series.dropna()
            if len(non_null) and getattr(non_null.iloc[0], "tzinfo", None) is not None:
                return "datetime_tz"
        return mapping[inferred]
    return "mixed"


def type_family(ltype: str) -> str:
    """Group logical types into families whose values can be compared directly."""
    if ltype in NUMERIC_TYPES:
        return "numeric"
    if ltype in TEMPORAL_TYPES:
        return "datetime"
    if ltype in TEXT_TYPES:
        return "string"
    return ltype


def compatible_types(left: str, right: str) -> bool:
    """True when two logical types can be compared without lossy coercion."""
    if left == right or "empty" in (left, right):
        return True
    family = type_family(left)
    if family != type_family(right):
        return False
    if family == "datetime":
        # Timezone-aware vs naive timestamps need an explicit timezone to compare.
        return {left, right} <= {"datetime", "date"}
    return True
