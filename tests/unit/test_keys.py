from __future__ import annotations

import numpy as np
import pandas as pd

from reconsi.keys import analyze_keys, canonical_strings, combined_key
from reconsi.keys.canonical import NULL_TOKEN, SEP, shape_of


def test_canonical_strings_unify_numeric_representations() -> None:
    assert canonical_strings(pd.Series([1, 2])).tolist() == ["1", "2"]
    assert canonical_strings(pd.Series([1.0, np.nan])).tolist() == ["1", None]
    assert canonical_strings(pd.Series([1.5])).tolist() == ["1.5"]
    assert canonical_strings(pd.Series(["001", None])).tolist() == ["001", None]
    ts = canonical_strings(pd.Series(pd.to_datetime(["2026-01-01", None])))
    assert ts.tolist() == ["2026-01-01T00:00:00", None]


def test_combined_key_composite_and_null() -> None:
    frame = pd.DataFrame({"a": [1, None], "b": ["x", "y"]})
    out = combined_key(frame, ["a", "b"]).tolist()
    assert out == [f"1{SEP}x", f"{NULL_TOKEN}{SEP}y"]


def test_shape_of() -> None:
    assert shape_of("CUST-00123") == "A-9"
    assert shape_of("ab 12") == "A_9"


def test_unique_one_to_one() -> None:
    left = pd.DataFrame({"id": [1, 2, 3]})
    right = pd.DataFrame({"id": [1, 2, 4]})
    ka = analyze_keys(left, right, ["id"])
    assert ka.relationship == "one-to-one"
    assert ka.left.is_unique and ka.right.is_unique
    assert (ka.common_keys, ka.left_only_keys, ka.right_only_keys) == (2, 1, 1)
    assert ka.naive_join_rows == 2 and ka.join_inflation == 0
    assert ka.left.multiplicity_distribution == {"1": 3}


def test_duplicates_and_many_to_many() -> None:
    left = pd.DataFrame({"id": [1, 1, 2, 3, 3, 3]})
    right = pd.DataFrame({"id": [1, 1, 1, 2, 3, 3]})
    ka = analyze_keys(left, right, ["id"])
    assert ka.relationship == "many-to-many"
    assert ka.left.duplicate_keys == 2
    assert ka.left.rows_in_duplicate_keys == 5
    assert ka.left.max_multiplicity == 3
    assert ka.left.mean_records_per_key == 2.0
    assert ka.left.multiplicity_distribution == {"1": 1, "2": 1, "3": 1}
    assert ka.naive_join_rows == 2 * 3 + 1 + 3 * 2
    assert ka.join_inflation == 13 - 3
    assert ka.left.duplicate_examples[0] == {"key": {"id": 3}, "count": 3}


def test_one_to_many_and_many_to_one() -> None:
    a = pd.DataFrame({"id": [1, 2]})
    b = pd.DataFrame({"id": [1, 1, 2]})
    assert analyze_keys(a, b, ["id"]).relationship == "one-to-many"
    assert analyze_keys(b, a, ["id"]).relationship == "many-to-one"


def test_null_blank_whitespace_case_and_leading_zeros() -> None:
    left = pd.DataFrame({"id": ["A1", " A2", "", None, "a3", "A3", "007"]})
    right = pd.DataFrame({"id": ["A1"]})
    ka = analyze_keys(left, right, ["id"])
    issues = ka.left.format_issues["id"]
    assert ka.left.null_keys == 1
    assert issues.blank == 1
    assert issues.whitespace == 1
    assert issues.case_variants == 2
    assert issues.leading_zeros == 1


def test_malformed_keys_detected_against_dominant_pattern() -> None:
    values = [f"CUST-{i:05d}" for i in range(50)] + ["CUST00051", "??"]
    ka = analyze_keys(pd.DataFrame({"id": values}), pd.DataFrame({"id": ["x"]}), ["id"])
    issues = ka.left.format_issues["id"]
    assert issues.dominant_pattern == "A-9"
    assert issues.malformed == 2
    assert "CUST00051" in issues.malformed_examples


def test_dtype_mismatch_is_reported_but_keys_still_compared() -> None:
    left = pd.DataFrame({"id": [1, 2, 3]})
    right = pd.DataFrame({"id": ["1", "2", "3"]})
    ka = analyze_keys(left, right, ["id"])
    assert ka.dtype_mismatches == [{"column": "id", "left": "integer", "right": "string"}]
    assert ka.common_keys == 3


def test_normalization_diagnosis_explains_unmatched_keys() -> None:
    left = pd.DataFrame({"id": ["00123", "00456", "ABC ", "x"]})
    right = pd.DataFrame({"id": ["123", "456", "abc", "y"]})
    ka = analyze_keys(left, right, ["id"])
    by_name = {d["normalization"]: d for d in ka.normalization_diagnosis}
    assert by_name["strip_leading_zeros"]["would_match"] == 2
    assert by_name["alphanumeric_only"]["would_match"] == 1
    assert "casefold" not in by_name  # "ABC " also needs trimming
    assert ka.normalization_diagnosis[0]["normalization"] == "strip_leading_zeros"


def test_composite_keys() -> None:
    left = pd.DataFrame({"d": ["2026-01-01", "2026-01-01"], "s": [1, 2]})
    right = pd.DataFrame({"d": ["2026-01-01", "2026-01-02"], "s": [1, 2]})
    ka = analyze_keys(left, right, ["d", "s"])
    assert ka.common_keys == 1 and ka.left.is_unique
    assert ka.to_dict()["keys"] == ["d", "s"]
