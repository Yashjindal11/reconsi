"""Vectorised value comparison for a single column pair."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from reconsi.comparison.options import DEFAULT_FLOAT_RELATIVE_TOLERANCE, ColumnOptions
from reconsi.core.dtypes import logical_type, type_family
from reconsi.core.types import MismatchType
from reconsi.keys.canonical import canonical_strings

STRING_NORMALIZERS: dict[str, Callable[[pd.Series], pd.Series]] = {
    "trim": lambda s: s.str.strip(),
    "lowercase": lambda s: s.str.lower(),
    "casefold": lambda s: s.str.casefold(),
    "collapse_whitespace": lambda s: s.str.replace(r"\s+", " ", regex=True).str.strip(),
    "unicode_nfc": lambda s: s.str.normalize("NFC"),
    "unicode_nfkc": lambda s: s.str.normalize("NFKC"),
    "strip_leading_zeros": lambda s: s.str.replace(r"^(\s*)0+(?=\d)", r"\1", regex=True),
}

# Normalisations tried (but never applied) to explain string mismatches.
_STRING_HINTS: list[tuple[str, list[str]]] = [
    ("trim", ["trim"]),
    ("casefold", ["casefold"]),
    ("trim + casefold", ["trim", "casefold"]),
    ("collapse_whitespace", ["collapse_whitespace"]),
    ("unicode_nfkc", ["unicode_nfkc"]),
    ("strip_leading_zeros", ["strip_leading_zeros"]),
]

_TRUE = frozenset({"true", "t", "yes", "y", "1"})
_FALSE = frozenset({"false", "f", "no", "n", "0"})


@dataclass
class ColumnComparison:
    """Element-wise comparison of aligned left/right values."""

    column: str
    kind: str
    equal: np.ndarray
    mismatch_type: np.ndarray
    within_tolerance: np.ndarray
    difference: np.ndarray | None = None
    relative_difference: np.ndarray | None = None
    datatype_mismatch: bool = False
    effective: dict[str, Any] = field(default_factory=dict)
    hints: list[dict[str, Any]] = field(default_factory=list)
    """Diagnostic clues, e.g. how many mismatches would vanish under an unconfigured normalisation."""


def resolve_kind(left: pd.Series, right: pd.Series, options: ColumnOptions) -> tuple[str, bool]:
    """Decide how to compare a column pair. Returns ``(kind, datatype_mismatch)``."""
    lt, rt = logical_type(left), logical_type(right)
    lf, rf = type_family(lt), type_family(rt)
    if "empty" in (lf, rf):
        lf = rf = rf if lf == "empty" else lf
    natural = lf if lf == rf else None
    mismatch = natural is None
    if options.type != "auto":
        return options.type, mismatch
    if natural in {"numeric", "datetime", "boolean", "string"}:
        return natural, False
    if natural == "empty":
        return "string", False
    return "string", True


def _null_masks(
    left: pd.Series, right: pd.Series, options: ColumnOptions
) -> tuple[np.ndarray, np.ndarray]:
    ln = left.isna().to_numpy()
    rn = right.isna().to_numpy()
    if options.empty_string_as_null:
        ln = ln | (left.astype(object) == "").to_numpy()
        rn = rn | (right.astype(object) == "").to_numpy()
    return ln, rn


def _finish(
    equal_values: np.ndarray,
    ln: np.ndarray,
    rn: np.ndarray,
    failed: np.ndarray,
    value_type: MismatchType,
    options: ColumnOptions,
) -> tuple[np.ndarray, np.ndarray]:
    both_null = ln & rn
    one_null = ln ^ rn
    equal = np.where(both_null, options.null_equals_null, equal_values & ~ln & ~rn & ~failed)
    mtype = np.full(len(equal), None, dtype=object)
    mtype[~equal & ~one_null & ~failed] = value_type.value
    mtype[~equal & failed] = MismatchType.DATATYPE.value
    mtype[~equal & one_null] = MismatchType.NULL.value
    mtype[both_null & ~equal] = MismatchType.NULL.value
    return equal.astype(bool), mtype


def _to_float(series: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Coerce to float64. Returns values and a mask of non-null values that failed to parse."""
    if series.dtype == bool or str(series.dtype) == "boolean":
        series = series.astype("Float64")
    numeric = pd.to_numeric(series, errors="coerce")
    values = numeric.to_numpy(dtype=float, na_value=np.nan)
    failed = series.notna().to_numpy() & np.isnan(values)
    return values, failed


def compare_numeric(
    column: str, left: pd.Series, right: pd.Series, options: ColumnOptions
) -> ColumnComparison:
    ln, rn = _null_masks(left, right, options)
    a, af = _to_float(left)
    b, bf = _to_float(right)
    failed = af | bf
    is_float = "float" in (logical_type(left), logical_type(right)) or failed.any()
    rel_tol = options.relative_tolerance
    if rel_tol is None:
        rel_tol = DEFAULT_FLOAT_RELATIVE_TOLERANCE if is_float else 0.0
    if options.decimals is not None:
        a = np.round(a, options.decimals)
        b = np.round(b, options.decimals)
    both_int = logical_type(left) == "integer" and logical_type(right) == "integer"
    with np.errstate(invalid="ignore", over="ignore", divide="ignore"):
        if both_int and options.decimals is None:
            # Exact integer arithmetic avoids float64 precision loss above 2**53.
            li = left.astype("Int64").to_numpy(dtype=np.int64, na_value=0)
            ri = right.astype("Int64").to_numpy(dtype=np.int64, na_value=0)
            exact = li == ri
            diff = (ri - li).astype(float)
        else:
            exact = a == b
            diff = b - a
        tol = np.maximum(options.absolute_tolerance, rel_tol * np.maximum(np.abs(a), np.abs(b)))
        close = np.abs(diff) <= tol
        rel = np.where(a != 0, diff / np.abs(a), np.nan)
    equal_values = exact | close
    equal, mtype = _finish(equal_values, ln, rn, failed, MismatchType.NUMERIC, options)
    within = equal & ~exact & ~ln & ~rn
    return ColumnComparison(
        column=column,
        kind="numeric",
        equal=equal,
        mismatch_type=mtype,
        within_tolerance=within,
        difference=np.where(ln | rn, np.nan, diff),
        relative_difference=np.where(ln | rn, np.nan, rel),
        effective={
            "absolute_tolerance": options.absolute_tolerance,
            "relative_tolerance": rel_tol,
            "decimals": options.decimals,
        },
    )


def _text(series: pd.Series) -> pd.Series:
    return canonical_strings(series).fillna("").astype(object)


def apply_normalizations(text: pd.Series, steps: list[str]) -> pd.Series:
    for step in steps:
        text = STRING_NORMALIZERS[step](text)
    return text


def compare_string(
    column: str, left: pd.Series, right: pd.Series, options: ColumnOptions
) -> ColumnComparison:
    ln, rn = _null_masks(left, right, options)
    a = apply_normalizations(_text(left), list(options.normalize))
    b = apply_normalizations(_text(right), list(options.normalize))
    exact = (_text(left) == _text(right)).to_numpy()
    equal_values = (a == b).to_numpy()
    failed = np.zeros(len(a), dtype=bool)
    equal, mtype = _finish(equal_values, ln, rn, failed, MismatchType.STRING, options)
    hints: list[dict[str, Any]] = []
    value_mismatch = mtype == MismatchType.STRING.value
    n_mismatch = int(value_mismatch.sum())
    if n_mismatch:
        ma, mb = a[value_mismatch], b[value_mismatch]
        for label, steps in _STRING_HINTS:
            if set(steps) <= set(options.normalize):
                continue
            resolved = int(
                (apply_normalizations(ma, steps) == apply_normalizations(mb, steps)).sum()
            )
            if resolved:
                hints.append(
                    {
                        "kind": "string_normalization",
                        "normalization": label,
                        "would_resolve": resolved,
                        "of_mismatches": n_mismatch,
                    }
                )
        hints.sort(key=lambda h: -int(h["would_resolve"]))
    return ColumnComparison(
        column=column,
        kind="string",
        equal=equal,
        mismatch_type=mtype,
        within_tolerance=equal & ~exact & ~ln & ~rn,
        effective={"normalize": list(options.normalize)},
        hints=hints,
    )


def _to_bool(series: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    out = np.zeros(len(series), dtype=bool)
    failed = np.zeros(len(series), dtype=bool)
    for i, value in enumerate(series.tolist()):
        if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NA:
            continue
        if isinstance(value, bool | np.bool_):
            out[i] = bool(value)
            continue
        token = str(value).strip().casefold()
        if token.endswith(".0"):
            token = token[:-2]
        if token in _TRUE:
            out[i] = True
        elif token not in _FALSE:
            failed[i] = True
    return out, failed


def compare_boolean(
    column: str, left: pd.Series, right: pd.Series, options: ColumnOptions
) -> ColumnComparison:
    ln, rn = _null_masks(left, right, options)
    a, af = _to_bool(left)
    b, bf = _to_bool(right)
    equal, mtype = _finish(a == b, ln, rn, af | bf, MismatchType.BOOLEAN, options)
    return ColumnComparison(
        column=column,
        kind="boolean",
        equal=equal,
        mismatch_type=mtype,
        within_tolerance=np.zeros(len(a), dtype=bool),
    )


def compare_column(
    column: str, left: pd.Series, right: pd.Series, options: ColumnOptions
) -> ColumnComparison:
    """Compare two aligned series according to ``options``."""
    left = left.reset_index(drop=True)
    right = right.reset_index(drop=True)
    kind, dtype_mismatch = resolve_kind(left, right, options)
    if kind == "numeric":
        result = compare_numeric(column, left, right, options)
    elif kind == "boolean":
        result = compare_boolean(column, left, right, options)
    elif kind == "string":
        result = compare_string(column, left, right, options)
    else:
        raise NotImplementedError(kind)
    result.datatype_mismatch = dtype_mismatch
    return result
