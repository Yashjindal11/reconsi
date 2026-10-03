from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from reconsi.comparison import ColumnOptions, compare_column
from reconsi.comparison.values import to_utc_naive


def cmp(a: object, b: object, **opts: object) -> object:
    return compare_column("t", pd.Series(a), pd.Series(b), ColumnOptions(**opts))


def test_naive_datetimes_exact() -> None:
    a = pd.to_datetime(["2026-10-03 10:00", "2026-10-03 11:00"])
    b = pd.to_datetime(["2026-10-03 10:00", "2026-10-03 11:05"])
    r = cmp(a, b)
    assert r.kind == "datetime"
    assert r.equal.tolist() == [True, False]
    assert r.difference.tolist() == [0.0, 300.0]


def test_timezone_aware_equivalence_utc_vs_ist() -> None:
    a = pd.Series(pd.to_datetime(["2026-10-03 10:00:00"]).tz_localize("UTC"))
    b = pd.Series(pd.to_datetime(["2026-10-03 15:30:00"]).tz_localize("Asia/Kolkata"))
    assert cmp(a, b).equal.tolist() == [True]


def test_string_dates_with_offsets() -> None:
    r = cmp(["2026-10-03T10:00:00Z"], ["2026-10-03T15:30:00+05:30"])
    assert r.kind == "string"  # strings are never parsed as dates unless asked
    r = cmp(["2026-10-03T10:00:00Z"], ["2026-10-03T15:30:00+05:30"], type="datetime")
    assert r.equal.tolist() == [True]


def test_naive_local_timestamps_with_configured_timezone() -> None:
    a = pd.Series(pd.to_datetime(["2026-10-03 10:00:00"]).tz_localize("UTC"))
    b = pd.Series(pd.to_datetime(["2026-10-03 15:30:00"]))
    r = cmp(a, b)
    assert not r.equal[0]
    assert any(h["kind"] == "timezone_assumption" for h in r.hints)
    r = cmp(a, b, timezone="Asia/Kolkata")
    assert r.equal[0] and not r.hints


def test_constant_offset_hint() -> None:
    a = pd.Series(pd.date_range("2026-01-01", periods=10, freq="h"))
    b = a + pd.Timedelta(hours=5, minutes=30)
    r = cmp(a, b)
    (hint,) = [h for h in r.hints if h["kind"] == "constant_offset"]
    assert hint["offset"] == "+05:30" and hint["share"] == 1.0


def test_precision_differences_and_tolerance() -> None:
    a = pd.Series(pd.to_datetime(["2026-01-01 10:00:00", "2026-01-01 10:00:00"]))
    b = pd.Series(pd.to_datetime(["2026-01-01 10:00:00.250", "2026-01-01 10:00:00.900"]))
    r = cmp(a, b)
    assert not r.equal.any()
    (hint,) = [h for h in r.hints if h["kind"] == "precision"]
    assert hint["precision"] == "second" and hint["would_resolve"] == 2
    r = cmp(a, b, tolerance_seconds=0.5)
    assert r.equal.tolist() == [True, False]
    assert r.within_tolerance.tolist() == [True, False]


def test_date_vs_datetime() -> None:
    a = pd.Series([dt.date(2026, 1, 1), dt.date(2026, 1, 2)], dtype=object)
    b = pd.Series(pd.to_datetime(["2026-01-01 00:00", "2026-01-02 13:45"]))
    r = cmp(a, b)
    assert r.equal.tolist() == [True, False]
    assert cmp(a, b, compare_as_date=True).equal.all()


def test_unparseable_datetimes_are_datatype_mismatches() -> None:
    r = cmp(["2026-01-01", "not a date", None], ["2026-01-01", "2026-01-02", None], type="datetime")
    assert r.equal.tolist() == [True, False, True]
    assert r.mismatch_type.tolist() == [None, "datatype", None]


def test_to_utc_naive_dst_ambiguity_becomes_failure() -> None:
    # 01:30 on the US fall-back night happens twice: refuse to guess.
    s = pd.Series(pd.to_datetime(["2026-11-01 01:30:00", "2026-11-01 12:00:00"]))
    values, failed, aware = to_utc_naive(s, "America/Chicago")
    assert aware and failed.tolist() == [True, False]
    assert values.iloc[1] == pd.Timestamp("2026-11-01 18:00:00")


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_resolution_independent(unit: str) -> None:
    a = pd.Series(pd.to_datetime(["2026-01-01 10:00:00"]).as_unit(unit))
    b = pd.Series(pd.to_datetime(["2026-01-01 10:00:00"]).as_unit("ns"))
    assert cmp(a, b).equal.all()
