from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from reconsi import Reconciliation, Status, reconcile
from reconsi.core.errors import ConfigurationError


@pytest.fixture
def spec_pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    a = pd.DataFrame(
        {"id": [1, 2, 3], "country": ["India", "USA", "UK"], "amount": [100, 200, 300]}
    )
    b = pd.DataFrame(
        {"id": [1, 2, 4], "country": ["India", "USA", "Canada"], "amount": [100, 250, 400]}
    )
    return a, b


def test_spec_basic_example(spec_pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(*spec_pair, keys=["id"])
    s = result.summary
    assert (s["matched_records"], s["value_mismatch_records"]) == (1, 1)
    assert (s["missing_right"], s["missing_left"]) == (1, 1)
    assert result.status == Status.FAIL
    assert result.matched["id"].tolist() == [1]
    assert result.missing_right["id"].tolist() == [3]
    assert result.missing_left["id"].tolist() == [4]
    assert result.missing_left["country"].tolist() == ["Canada"]
    (mm,) = result.record_mismatches()
    assert mm.key == {"id": 2} and mm.column == "amount"
    assert (mm.left_value, mm.right_value, mm.difference) == (200, 250, 50.0)
    assert mm.relative_difference == pytest.approx(0.25)
    assert mm.mismatch_type == "numeric"
    assert "1 value mismatches" in repr(result)


def test_perfect_match_passes() -> None:
    frame = pd.DataFrame({"id": range(100), "v": np.arange(100) * 1.5})
    result = reconcile(frame, frame.copy(), keys="id")
    assert result.status == Status.PASS
    assert result.summary["match_percentage"] == 100.0
    assert result.value_mismatches.empty and result.missing_left.empty


def test_compare_columns_subset_and_column_statistics(
    spec_pair: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    result = reconcile(*spec_pair, keys=["id"], compare_columns=["country"])
    assert list(result.columns) == ["country"]
    assert result.summary["value_mismatch_records"] == 0
    stats = result.column_statistics
    assert stats.loc[0, "classification"] == "exact_match"


def test_numeric_tolerance_via_keyword() -> None:
    a = pd.DataFrame({"id": [1, 2], "v": [100.0, 100.0]})
    b = pd.DataFrame({"id": [1, 2], "v": [100.004, 100.5]})
    result = reconcile(a, b, keys="id", absolute_tolerance=0.01)
    stats = result.columns["v"]
    assert (stats.matches, stats.mismatches, stats.within_tolerance) == (1, 1, 1)
    assert stats.totals is not None and stats.totals["difference"] == pytest.approx(0.504)


def test_column_mapping(spec_pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    a, b = spec_pair
    b = b.rename(columns={"id": "cust_id", "amount": "sales_amt"})
    result = reconcile(a, b, keys=["id"], column_mapping={"id": "cust_id", "amount": "sales_amt"})
    assert result.summary["value_mismatch_records"] == 1
    assert result.schema.renamed == {"id": "cust_id", "amount": "sales_amt"}
    assert "sales_amt" in result.schema.right.column_names


def test_right_keys_with_different_names() -> None:
    a = pd.DataFrame({"id": [1, 2], "v": [1, 2]})
    b = pd.DataFrame({"key": [1, 2], "v": [1, 3]})
    result = reconcile(a, b, keys=["id"], right_keys=["key"])
    assert result.summary["value_mismatch_records"] == 1


def test_null_keys_never_match() -> None:
    a = pd.DataFrame({"id": [1.0, None], "v": [1, 2]})
    b = pd.DataFrame({"id": [1.0, None], "v": [1, 2]})
    result = reconcile(a, b, keys="id")
    s = result.summary
    assert s["matched_records"] == 1 and s["missing_left"] == 1 and s["missing_right"] == 1
    assert result.keys.left.null_keys == 1


def test_key_dtype_mismatch_is_cast_and_noted() -> None:
    a = pd.DataFrame({"id": [1, 2, 3], "v": [1, 2, 3]})
    b = pd.DataFrame({"id": ["1", "2", "003"], "v": [1, 2, 3]})
    result = reconcile(a, b, keys="id")
    assert result.summary["matched_records"] == 2
    assert any(n["kind"] == "keys_cast_to_text" for n in result.notes)
    diag = result.keys.normalization_diagnosis
    assert diag and diag[0]["normalization"] == "strip_leading_zeros"


def test_key_normalize_opt_in() -> None:
    a = pd.DataFrame({"id": [" A1", "b2"], "v": [1, 2]})
    b = pd.DataFrame({"id": ["a1", "B2"], "v": [1, 2]})
    assert reconcile(a, b, keys="id").summary["matched_records"] == 0
    result = reconcile(a, b, keys="id", key_normalize=["trim", "casefold"])
    assert result.summary["matched_records"] == 2
    assert any(n["kind"] == "keys_normalized" for n in result.notes)


@pytest.fixture
def dup_pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    a = pd.DataFrame({"id": [1, 1, 2, 3], "v": [10, 20, 5, 7]})
    b = pd.DataFrame({"id": [1, 1, 2, 3], "v": [20, 10, 5, 8]})
    return a, b


def test_strict_sets_duplicates_aside(dup_pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(*dup_pair, keys="id")
    s = result.summary
    assert s["ambiguous_records"] == 4
    assert s["matched_records"] == 1 and s["value_mismatch_records"] == 1
    assert result.duplicate_keys.to_dict(orient="records") == [
        {"id": 1, "left_count": 2, "right_count": 2}
    ]
    assert set(result.ambiguous["_source"]) == {"left", "right"}


def test_first_and_last(dup_pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    first = reconcile(*dup_pair, keys="id", duplicate_strategy="first")
    assert first.summary["value_mismatch_records"] == 2  # id 1 (10 vs 20) and id 3
    last = reconcile(*dup_pair, keys="id", duplicate_strategy="last")
    assert last.summary["value_mismatch_records"] == 2


def test_multiset_pairs_identical_rows(dup_pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(*dup_pair, keys="id", duplicate_strategy="multiset")
    assert result.summary["matched_records"] == 3
    assert result.summary["value_mismatch_records"] == 1
    assert "_occurrence" in result.key_columns


def test_aggregate_strategy(dup_pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(*dup_pair, keys="id", duplicate_strategy="aggregate")
    assert result.summary["matched_records"] == 2
    assert result.value_mismatches["id"].tolist() == [3]


def test_grouped_strategy_compares_row_counts() -> None:
    a = pd.DataFrame({"id": [1, 1, 2], "v": [10, 20, 5]})
    b = pd.DataFrame({"id": [1, 2], "v": [30, 5]})
    result = reconcile(a, b, keys="id", duplicate_strategy="grouped")
    assert set(result.columns) == {"v", "_row_count"}
    assert result.columns["v"].mismatches == 0
    assert result.columns["_row_count"].mismatches == 1


def test_aggregation_reconciliation_spec_example() -> None:
    transactions = pd.DataFrame(
        {
            "date": ["2026-10-01"] * 3 + ["2026-10-02"] * 2,
            "revenue": [100.0, 50.0, 25.0, 10.0, 15.0],
        }
    )
    daily = pd.DataFrame(
        {"date": ["2026-10-01", "2026-10-02"], "revenue": [175.0, 30.0], "orders": [3, 2]}
    )
    result = reconcile(
        left=transactions,
        right=daily,
        left_group_by=["date"],
        right_keys=["date"],
        aggregations={"revenue": "sum", "orders": "count"},
    )
    assert set(result.columns) == {"revenue", "orders"}
    assert result.columns["orders"].mismatches == 0
    assert result.columns["revenue"].mismatches == 1
    assert result.value_mismatches.iloc[0]["difference"] == pytest.approx(5.0)
    assert result.summary["left_rows"] == 5 and result.summary["left_records"] == 2


def test_files_end_to_end(tmp_path: Path, spec_pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    a, b = spec_pair
    a.to_csv(tmp_path / "a.csv", index=False)
    b.to_parquet(tmp_path / "b.parquet")
    result = reconcile(tmp_path / "a.csv", tmp_path / "b.parquet", keys="id")
    assert result.summary["matched_records"] == 1
    assert result.metadata["left"]["format"] == "csv"
    doc = json.loads(result.to_json())
    assert doc["status"] == "FAIL" and doc["summary"]["missing_left"] == 1


def test_config_paths_resolve_relative_to_base_dir(tmp_path: Path) -> None:
    pd.DataFrame({"id": [1], "v": [1]}).to_csv(tmp_path / "a.csv", index=False)
    pd.DataFrame({"id": [1], "v": [1]}).to_csv(tmp_path / "b.csv", index=False)
    job = Reconciliation(
        keys="id", left={"path": "a.csv"}, right={"path": "b.csv"}, base_dir=tmp_path
    )
    assert job.run().status == Status.PASS


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"keys": "missing"}, "key columns"),
        ({"keys": "id", "compare_columns": ["nope"]}, "compare columns"),
        ({"keys": "id", "compare_columns": ["id"]}, "key columns cannot"),
        ({"keys": "id", "dimensions": ["nope"]}, "dimensions"),
        ({"keys": "id", "date_column": "nope"}, "date_column"),
        ({"keys": "id", "column_mapping": {"country": "amount"}}, "duplicate column"),
    ],
)
def test_configuration_errors(
    spec_pair: tuple[pd.DataFrame, pd.DataFrame], kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        reconcile(*spec_pair, **kwargs)


def test_missing_dataset_error() -> None:
    with pytest.raises(ConfigurationError, match="no left dataset"):
        Reconciliation(keys="id")


def test_detail_rows_truncated_but_counts_exact() -> None:
    a = pd.DataFrame({"id": range(2000), "v": 0})
    b = pd.DataFrame({"id": range(2000), "v": 1})
    result = reconcile(a, b, keys="id", max_detail_rows=0)
    assert result.columns["v"].mismatches == 2000
    assert result.value_mismatches.empty
    assert any(n["kind"] == "truncated" for n in result.notes)


def test_chunked_join_gives_same_answer() -> None:
    rng = np.random.default_rng(1)
    a = pd.DataFrame({"id": range(5000), "v": rng.normal(size=5000)})
    b = a.sample(frac=0.95, random_state=2).copy()
    b.loc[b.index[:100], "v"] += 1
    one = reconcile(a, b, keys="id")
    many = reconcile(a, b, keys="id", chunk_size=1000)
    assert one.summary == many.summary
    assert one.columns["v"].to_dict() == many.columns["v"].to_dict()
