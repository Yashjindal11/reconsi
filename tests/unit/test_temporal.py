from __future__ import annotations

import numpy as np
import pandas as pd

from reconsi import reconcile
from reconsi.temporal import detect_change_points


def test_change_point_found_at_step() -> None:
    n = np.full(30, 1000)
    rng = np.random.default_rng(0)
    k = np.concatenate([rng.binomial(1000, 0.002, 14), rng.binomial(1000, 0.05, 16)])
    (cp,) = detect_change_points(k, n, seed=1)
    assert cp["index"] == 14
    assert cp["rate_before"] < 0.005 < 0.04 < cp["rate_after"]
    assert cp["p_value"] < 0.01


def test_no_change_point_in_stable_series() -> None:
    rng = np.random.default_rng(2)
    n = np.full(30, 1000)
    k = rng.binomial(1000, 0.01, 30)
    assert detect_change_points(k, n, seed=3) == []


def test_short_or_degenerate_series() -> None:
    assert detect_change_points(np.array([1, 2]), np.array([10, 10])) == []
    assert detect_change_points(np.zeros(10), np.full(10, 10)) == []


def _daily(
    days: int = 20, per_day: int = 500, bad_day: int | None = None, step_from: int | None = None
):
    rng = np.random.default_rng(4)
    dates = pd.date_range("2026-09-01", periods=days, freq="D")
    left = pd.DataFrame(
        {
            "id": np.arange(days * per_day),
            "date": np.repeat(dates, per_day),
            "amount": rng.uniform(1, 100, days * per_day).round(2),
        }
    )
    right = left.copy()
    day_idx = np.repeat(np.arange(days), per_day)
    noise = rng.random(len(right)) < 0.002
    if bad_day is not None:
        noise |= (day_idx == bad_day) & (rng.random(len(right)) < 0.06)
    if step_from is not None:
        noise |= (day_idx >= step_from) & (rng.random(len(right)) < 0.05)
    right.loc[noise, "amount"] += 1
    return left, right


def test_timeline_flags_anomalous_day() -> None:
    result = reconcile(*_daily(bad_day=12), keys="id")
    temporal = result.analyses["temporal"]
    assert result.metadata["date_column"] == "date"
    assert len(temporal["periods"]) == 20
    (anomaly,) = temporal["anomalous_periods"]
    assert str(anomaly["period"]).startswith("2026-09-13")


def test_timeline_change_point_message() -> None:
    result = reconcile(*_daily(step_from=10), keys="id")
    cps = result.analyses["temporal"]["change_points"]
    assert cps and str(cps[0]["period"]).startswith("2026-09-11")
    assert "not why" in cps[0]["message"]


def test_weekly_frequency_and_string_dates() -> None:
    left, right = _daily()
    left["date"] = left["date"].dt.strftime("%Y-%m-%d")
    right["date"] = right["date"].dt.strftime("%Y-%m-%d")
    result = reconcile(left, right, keys="id", time_frequency="W")
    assert result.metadata["date_column"] == "date"
    assert 3 <= len(result.analyses["temporal"]["periods"]) <= 4


def test_no_temporal_without_dates() -> None:
    frame = pd.DataFrame({"id": [1, 2], "v": [1, 2]})
    assert "temporal" not in reconcile(frame, frame, keys="id").analyses
