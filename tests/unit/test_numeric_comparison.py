from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from reconsi.comparison import ColumnOptions, compare_column


def cmp(a: list[object], b: list[object], **opts: object) -> object:
    return compare_column("x", pd.Series(a), pd.Series(b), ColumnOptions(**opts))


def test_exact_integers() -> None:
    r = cmp([1, 2, 3], [1, 2, 4])
    assert r.kind == "numeric"
    assert r.equal.tolist() == [True, True, False]
    assert r.mismatch_type.tolist() == [None, None, "numeric"]
    assert r.difference.tolist() == [0.0, 0.0, 1.0]
    assert r.relative_difference[2] == pytest.approx(1 / 3)
    assert r.effective["relative_tolerance"] == 0.0


def test_large_integers_compared_exactly() -> None:
    big = 2**60
    r = cmp([big], [big + 1])
    assert r.equal.tolist() == [False]


def test_float_representation_is_not_a_mismatch() -> None:
    r = cmp([0.1 + 0.2], [0.3])
    assert r.equal.tolist() == [True]
    # Representation-level noise counts as an exact match with zero difference.
    assert r.within_tolerance.tolist() == [False]
    assert r.difference.tolist() == [0.0]


def test_absolute_tolerance() -> None:
    r = cmp([100.0, 100.0], [100.004, 100.02], absolute_tolerance=0.01)
    assert r.equal.tolist() == [True, False]
    assert r.within_tolerance.tolist() == [True, False]


def test_relative_tolerance_is_symmetric() -> None:
    r1 = cmp([100.0], [100.1], relative_tolerance=0.001)
    r2 = cmp([100.1], [100.0], relative_tolerance=0.001)
    assert r1.equal.tolist() == r2.equal.tolist() == [True]
    assert cmp([100.0], [100.2], relative_tolerance=0.001).equal.tolist() == [False]


def test_decimals_rounding_only_when_configured() -> None:
    assert cmp([1.004], [1.0]).equal.tolist() == [False]
    assert cmp([1.004], [1.0], decimals=2).equal.tolist() == [True]


def test_nulls_are_explicit() -> None:
    r = cmp([None, 1.0, None, 0.0], [None, None, 1.0, None])
    assert r.equal.tolist() == [True, False, False, False]
    assert r.mismatch_type.tolist() == [None, "null", "null", "null"]
    assert np.isnan(r.difference[1])
    r2 = cmp([None], [None], null_equals_null=False, type="numeric")
    assert r2.equal.tolist() == [False] and r2.mismatch_type.tolist() == ["null"]


def test_zero_is_not_null() -> None:
    assert cmp([0], [None]).mismatch_type.tolist() == ["null"]


def test_unparseable_values_are_datatype_mismatches() -> None:
    r = cmp(["1.5", "abc"], [1.5, 2.0], type="numeric")
    assert r.equal.tolist() == [True, False]
    assert r.mismatch_type.tolist() == [None, "datatype"]
    assert r.datatype_mismatch


def test_relative_difference_undefined_for_zero_base() -> None:
    r = cmp([0.0], [5.0])
    assert np.isnan(r.relative_difference[0])
    assert r.difference[0] == 5.0


def test_invalid_options_rejected() -> None:
    with pytest.raises(ValidationError):
        ColumnOptions(absolute_tolerance=-1)
    with pytest.raises(ValidationError):
        ColumnOptions(timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        ColumnOptions(bogus=1)  # type: ignore[call-arg]


def test_merged_options_only_override_set_fields() -> None:
    base = ColumnOptions(absolute_tolerance=0.5, normalize=["trim"])
    merged = base.merged(ColumnOptions(relative_tolerance=0.1))
    assert merged.absolute_tolerance == 0.5 and merged.relative_tolerance == 0.1
    assert merged.normalize == ["trim"]
    assert base.merged(None) is base


@given(
    st.lists(st.floats(allow_nan=False, allow_infinity=False, width=32), min_size=1, max_size=20),
    st.floats(min_value=0, max_value=10),
)
def test_values_always_match_themselves(values: list[float], tol: float) -> None:
    r = cmp(values, list(values), absolute_tolerance=tol)
    assert r.equal.all()


@given(
    st.floats(-1e6, 1e6, allow_nan=False),
    st.floats(-1e6, 1e6, allow_nan=False),
    st.floats(0, 100),
)
def test_comparison_is_symmetric(a: float, b: float, tol: float) -> None:
    assert (
        cmp([a], [b], absolute_tolerance=tol).equal[0]
        == cmp([b], [a], absolute_tolerance=tol).equal[0]
    )
