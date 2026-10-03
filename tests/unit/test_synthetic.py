from __future__ import annotations

import pandas as pd
import pytest

from reconsi import reconcile
from reconsi.synthetic import generate_base, generate_reconciliation_pair


def test_base_is_deterministic_and_realistic() -> None:
    a, b = generate_base(500, seed=3), generate_base(500, seed=3)
    pd.testing.assert_frame_equal(a, b)
    assert a["order_id"].is_unique
    assert (a["revenue"] == (a["quantity"] * a["unit_price"]).round(2)).all()


def test_clean_pair_matches_perfectly() -> None:
    pair = generate_reconciliation_pair(2000, seed=1)
    result = reconcile(pair.left, pair.right, keys=pair.keys)
    assert result.summary["matched_records"] == 2000
    assert result.status.value == "PASS"


def test_ground_truth_is_recovered_exactly() -> None:
    pair = generate_reconciliation_pair(
        5000,
        missing_rate=0.02,
        extra_rate=0.01,
        mismatch_rate=0.01,
        duplicate_rate=0.005,
        timestamp_shift_rate=0.004,
        category_change_rate=0.004,
        string_format_rate=0.004,
        seed=2,
    )
    t = pair.truth
    sizes = t.to_dict()
    assert sizes["missing_from_right"] == 100 and sizes["missing_from_left"] == 50
    assert sizes["duplicated_keys"] == 25
    result = reconcile(pair.left, pair.right, keys=pair.keys, duplicate_strategy="first")
    assert set(result.missing_right["order_id"]) == t.missing_from_right
    assert set(result.missing_left["order_id"]) == t.missing_from_left
    found = set(
        zip(result.value_mismatches["order_id"], result.value_mismatches["column"], strict=True)
    )
    assert found == t.changed_cells()
    assert set(result.duplicate_keys["order_id"]) == t.duplicated_keys


def test_corruption_sets_are_disjoint() -> None:
    pair = generate_reconciliation_pair(
        3000, missing_rate=0.05, mismatch_rate=0.05, duplicate_rate=0.05, seed=4
    )
    changed = {k for k, _ in pair.truth.value_changes}
    assert not changed & pair.truth.missing_from_right
    assert not pair.truth.duplicated_keys & pair.truth.missing_from_right


def test_bias_segment_missing_segment_incident() -> None:
    pair = generate_reconciliation_pair(
        6000,
        bias=0.025,
        bias_segment=("region", "West"),
        missing_rate=0.01,
        missing_segment=("channel", "phone"),
        incident_days=(10, 14),
        seed=5,
    )
    t = pair.truth
    assert t.systematic == {"revenue": 0.025} and t.segment == ("region", "West")
    left = pair.left.set_index("order_id")
    assert set(left.loc[list(t.missing_from_right), "channel"]) == {"phone"}
    biased = [k for (k, c), v in t.value_changes.items() if v == "bias"]
    assert set(left.loc[biased, "region"]) == {"West"}
    assert t.incident_dates == ("2026-09-11", "2026-09-15")


def test_schema_changes_and_rounding() -> None:
    pair = generate_reconciliation_pair(1000, schema_changes=True, rounding_rate=0.05, seed=6)
    assert "discount" in pair.right.columns and "qty" in pair.right.columns
    assert "status" not in pair.right.columns
    kinds = set(pair.truth.value_changes.values())
    assert kinds == {"rounding"}
    result = reconcile(
        pair.left,
        pair.right,
        keys="order_id",
        column_mapping={"quantity": "qty"},
        absolute_tolerance=0.5,
    )
    assert result.columns["revenue"].mismatches == 0
    assert result.columns["revenue"].within_tolerance > 0


@pytest.mark.parametrize("rate", [0.0, 0.5])
def test_rates_scale(rate: float) -> None:
    pair = generate_reconciliation_pair(200, missing_rate=rate, seed=0)
    assert len(pair.truth.missing_from_right) == round(rate * 200)
