from __future__ import annotations

import pandas as pd

from reconsi.schema import (
    compare_schemas,
    inspect_schema,
    name_similarity,
    normalized_name,
    suggest_column_matches,
)


def test_inspect_schema() -> None:
    frame = pd.DataFrame({"id": [1, 2], "name": ["a", None], "amt": [1.0, 2.0]})
    schema = inspect_schema(frame, "a")
    assert schema.row_count == 2
    assert schema.column_names == ["id", "name", "amt"]
    name = schema.column("name")
    assert name.nullable and name.null_count == 1 and name.logical_type == "string"
    assert schema.to_dict()["column_count"] == 3


def test_compare_schemas_added_removed_dtype_order() -> None:
    left = pd.DataFrame({"id": [1], "legacy_status": ["x"], "revenue": [1], "region": ["W"]})
    right = pd.DataFrame(
        {"id": [1], "region": ["W"], "revenue": [1.5], "discount": [0.1], "discount_reason": ["a"]}
    )
    diff = compare_schemas(left, right)
    assert diff.added == ["discount", "discount_reason"]
    assert diff.removed == ["legacy_status"]
    assert diff.common == ["id", "revenue", "region"]
    assert diff.order_changed
    (change,) = diff.dtype_changes
    assert change.column == "revenue" and change.compatible
    assert not diff.identical
    out = diff.to_dict()
    assert out["left"]["column_count"] == 4 and out["right"]["column_count"] == 5


def test_compare_schemas_with_mapping_and_nullability() -> None:
    left = pd.DataFrame({"customer_id": [1, 2], "revenue": [1.0, 2.0]})
    right = pd.DataFrame({"cust_id": [1, 2], "revenue": [1.0, None]})
    diff = compare_schemas(left, right, column_mapping={"customer_id": "cust_id"})
    assert diff.common == ["customer_id", "revenue"]
    assert diff.renamed == {"customer_id": "cust_id"}
    assert diff.nullability_changes[0]["column"] == "revenue"
    assert diff.right.column_names == ["cust_id", "revenue"]


def test_identical_schema() -> None:
    frame = pd.DataFrame({"a": [1]})
    assert compare_schemas(frame, frame.copy()).identical


def test_name_normalisation_expands_abbreviations() -> None:
    assert normalized_name("custID") == "customer_id"
    assert normalized_name("txn_dt") == "transaction_date"
    assert name_similarity("sales_amt", "sales_amount") == 1.0
    assert name_similarity("cust_id", "region") < 0.5


def test_suggest_column_matches() -> None:
    left = pd.DataFrame(
        {
            "customer_id": [1, 2, 3, 4],
            "sales_amount": [10.0, 20.0, 30.0, 40.0],
            "transaction_date": pd.to_datetime(["2026-01-01"] * 4),
        }
    )
    right = pd.DataFrame(
        {
            "cust_id": [1, 2, 3, 5],
            "sales_amt": [10.0, 20.0, 31.0, 40.0],
            "txn_dt": pd.to_datetime(["2026-01-01"] * 4),
            "unrelated": ["x", "y", "z", "w"],
        }
    )
    pairs = {(s.left, s.right) for s in suggest_column_matches(left, right)}
    assert pairs == {
        ("customer_id", "cust_id"),
        ("sales_amount", "sales_amt"),
        ("transaction_date", "txn_dt"),
    }


def test_schema_diff_includes_suggestions_for_unmatched_columns() -> None:
    left = pd.DataFrame({"id": [1, 2], "sales_amount": [1.0, 2.0]})
    right = pd.DataFrame({"id": [1, 2], "sales_amt": [1.0, 2.0]})
    diff = compare_schemas(left, right)
    (s,) = diff.suggestions
    assert (s.left, s.right) == ("sales_amount", "sales_amt")
    assert diff.to_dict()["suggested_column_matches"][0]["label"] == "suggestion"
