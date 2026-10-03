from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from reconsi import reconcile
from reconsi.statistics.bias import detect_bias
from reconsi.statistics.distributions import (
    categorical_distribution,
    compare_distributions,
    numeric_distribution,
)
from reconsi.statistics.intervals import describe_differences, wilson_interval


def test_wilson_interval() -> None:
    lo, hi = wilson_interval(0, 100)
    assert lo == 0.0 and 0.0 < hi < 0.05
    lo, hi = wilson_interval(50, 100)
    assert lo < 0.5 < hi
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_describe_differences() -> None:
    d = describe_differences(np.array([1.0, -1.0, 2.0, np.nan, 0.0]))
    assert d["count"] == 4 and d["positive"] == 2 and d["negative"] == 1 and d["zero"] == 1
    assert d["mean_absolute"] == 1.0 and d["p50"] == 0.5
    assert describe_differences(np.array([])) == {"count": 0}


def test_bias_proportional_shift_detected() -> None:
    rng = np.random.default_rng(0)
    a = rng.uniform(100, 1000, 500)
    b = a * 1.025
    out = detect_bias(b - a, (b - a) / a)
    assert out["systematic"] and out["direction"] == "right_higher"
    assert out["proportional"] and out["median_relative_difference"] == pytest.approx(0.025)
    assert "2.50%" in out["message"]
    assert out["label"] == "statistically_supported"


def test_bias_constant_offset() -> None:
    d = np.full(50, -3.0)
    out = detect_bias(d, None)
    assert out["systematic"] and out["direction"] == "right_lower" and out["constant_offset"]


def test_random_noise_is_not_systematic() -> None:
    rng = np.random.default_rng(1)
    out = detect_bias(rng.normal(0, 1, 400), None)
    assert out["tested"] and not out["systematic"]


def test_bias_not_tested_with_few_pairs() -> None:
    out = detect_bias(np.array([1.0, 2.0, 0.0]), None)
    assert not out["tested"] and "fewer than" in out["reason"]


def test_numeric_distribution_shift() -> None:
    rng = np.random.default_rng(2)
    same = numeric_distribution(
        pd.Series(rng.normal(0, 1, 2000)), pd.Series(rng.normal(0, 1, 2000)), 0.01
    )
    assert same["tested"] and not same["shift"]
    shifted = numeric_distribution(
        pd.Series(rng.normal(0, 1, 2000)), pd.Series(rng.normal(0.5, 1, 2000)), 0.01
    )
    assert shifted["shift"] and shifted["standardized_mean_difference"] > 0.3
    assert shifted["left"]["median"] < shifted["right"]["median"]


def test_categorical_distribution_shift_and_lumping() -> None:
    rng = np.random.default_rng(3)
    a = pd.Series(rng.choice(["E", "W", "S"], 3000, p=[0.4, 0.3, 0.3]))
    b = pd.Series(rng.choice(["E", "W", "S"], 3000, p=[0.2, 0.5, 0.3]))
    out = categorical_distribution(a, b, 0.01)
    assert out["shift"] and out["jensen_shannon_divergence"] > 0.02
    many = pd.Series([f"L{i}" for i in range(100)])
    lumped = categorical_distribution(many, many, 0.01, max_levels=10)
    assert len(lumped["levels"]) == 10 and lumped["levels"][-1]["level"] == "(other)"


def test_compare_distributions_skips_unsuitable_columns() -> None:
    left = pd.DataFrame(
        {"x": [1.0, 2.0, 3.0], "t": pd.to_datetime(["2026-01-01"] * 3), "c": list("abc")}
    )
    out = compare_distributions(left, left, ["x", "t", "c", "missing"])
    assert set(out) == {"x", "c"}


@pytest.fixture
def regional() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(4)
    n = 4000
    left = pd.DataFrame(
        {
            "id": np.arange(n),
            "region": rng.choice(["East", "West", "South", "North"], n),
            "product": rng.choice(["Basic", "Premium"], n),
            "revenue": rng.uniform(10, 100, n).round(2),
        }
    )
    right = left.copy()
    west = right["region"] == "West"
    idx = right.index[west][:300]
    right.loc[idx, "revenue"] += 5
    others = right.index[~west][:20]
    right.loc[others, "revenue"] += 5
    premium_west = right.index[(right["product"] == "Premium")][:150]
    right = right.drop(premium_west[:150])
    return left, right


def test_concentration_identifies_segment(regional: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(*regional, keys="id")
    assert set(result.dimensions) == {"region", "product"}
    conc = {c["dimension"]: c for c in result.analyses["concentration"]}
    assert conc["region"]["concentrated"]
    assert conc["region"]["top_level"]["level"] == "West"
    assert "West accounts for" in conc["region"]["message"]


def test_drill_down_and_recursive(regional: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(*regional, keys="id")
    table = result.drill_down("region")
    assert table.iloc[0]["region"] == "West"
    assert {"records", "matched", "value_mismatch", "problem_rate", "lift"} <= set(table.columns)
    sub = result.drill_down("product", where={"region": "West"})
    assert sub["records"].sum() == table.loc[table["region"] == "West", "records"].iloc[0]
    both = result.drill_down("region", "product")
    assert len(both) == 8
    with pytest.raises(KeyError, match="unknown dimension"):
        result.drill_down("nope")


def test_unmatched_population(regional: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(*regional, keys="id")
    pop = result.analyses["unmatched_population"]["missing_from_right"]
    assert pop["missing_records"] == 150
    product = next(d for d in pop["dimensions"] if d["dimension"] == "product")
    assert product["significant"]
    assert product["over_represented"][0]["level"] == "Premium"


def test_largest_differences(regional: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    left, right = regional
    right = right.copy()
    right.loc[right.index[right["region"] != "West"][-1], "revenue"] -= 50
    result = reconcile(left, right, keys="id")
    top = result.largest_differences("revenue", n=3)
    assert len(top) == 3 and abs(top.iloc[0]["difference"]) >= abs(top.iloc[1]["difference"])
    neg = result.largest_differences("revenue", by="negative", n=1)
    assert neg.iloc[0]["difference"] == pytest.approx(-50)
    assert result.largest_differences("revenue", by="positive", n=1).iloc[0]["difference"] > 0
    assert len(result.largest_differences("revenue", by="relative", n=2)) == 2
    assert "revenue" in result.analyses["largest_differences"]
    assert result.largest_differences("region").empty
    with pytest.raises(KeyError):
        result.largest_differences("nope")
    with pytest.raises(ValueError, match="by must be"):
        result.largest_differences("revenue", by="sideways")  # type: ignore[arg-type]


def test_engine_bias_and_distribution_analyses() -> None:
    rng = np.random.default_rng(5)
    left = pd.DataFrame({"id": range(1000), "amount": rng.uniform(100, 200, 1000)})
    right = left.assign(amount=left["amount"] * 1.025)
    result = reconcile(left, right, keys="id")
    assert result.analyses["bias"]["amount"]["systematic"]
    dist = result.analyses["distributions"]
    assert dist["sampled"] is False and dist["columns"]["amount"]["tested"]
