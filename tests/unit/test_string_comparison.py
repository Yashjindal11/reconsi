from __future__ import annotations

import pandas as pd

from reconsi.comparison import ColumnOptions, compare_column


def cmp(a: list[object], b: list[object], **opts: object) -> object:
    return compare_column("x", pd.Series(a), pd.Series(b), ColumnOptions(**opts))


NAMES = ["United Airlines", " United Airlines ", "UNITED AIRLINES", "United  Airlines"]


def test_exact_by_default_distinguishes_variants() -> None:
    r = cmp(["United Airlines"] * 4, NAMES)
    assert r.kind == "string"
    assert r.equal.tolist() == [True, False, False, False]
    assert set(r.mismatch_type.tolist()) == {None, "string"}


def test_trim_and_case_insensitive() -> None:
    assert cmp(["United Airlines"] * 4, NAMES, normalize=["trim"]).equal.tolist() == [
        True,
        True,
        False,
        False,
    ]
    r = cmp(["United Airlines"] * 4, NAMES, normalize=["trim", "casefold", "collapse_whitespace"])
    assert r.equal.all()
    assert r.within_tolerance.tolist() == [False, True, True, True]
    assert r.effective["normalize"] == ["trim", "casefold", "collapse_whitespace"]


def test_unicode_normalization() -> None:
    composed, decomposed = "caf\u00e9", "cafe\u0301"
    assert not cmp([composed], [decomposed]).equal[0]
    assert cmp([composed], [decomposed], normalize=["unicode_nfc"]).equal[0]
    assert cmp(["\uff21"], ["A"], normalize=["unicode_nfkc"]).equal[0]


def test_strip_leading_zeros_and_lowercase() -> None:
    assert cmp(["00123"], ["123"], normalize=["strip_leading_zeros"]).equal[0]
    assert cmp(["ABC"], ["abc"], normalize=["lowercase"]).equal[0]


def test_hints_suggest_but_never_apply_normalisation() -> None:
    r = cmp(["a", "b", "c"], [" a", "B", "x"])
    assert r.equal.tolist() == [False, False, False]
    hints = {h["normalization"]: h["would_resolve"] for h in r.hints}
    assert hints["trim"] == 1 and hints["casefold"] == 1 and hints["trim + casefold"] == 2
    assert r.hints[0]["normalization"] == "trim + casefold"
    assert r.hints[0]["of_mismatches"] == 3


def test_configured_normalisations_are_not_hinted() -> None:
    r = cmp(["a"], [" A"], normalize=["trim"])
    assert {h["normalization"] for h in r.hints} == {"casefold", "trim + casefold"}


def test_empty_string_is_not_null_unless_configured() -> None:
    r = cmp(["", None], [None, ""])
    assert r.equal.tolist() == [False, False]
    assert r.mismatch_type.tolist() == ["null", "null"]
    assert cmp(["", None], [None, ""], empty_string_as_null=True).equal.all()


def test_cross_type_values_compared_canonically_and_flagged() -> None:
    r = cmp([1, 2], ["1", "3"])
    assert r.kind == "string" and r.datatype_mismatch
    assert r.equal.tolist() == [True, False]


def test_boolean_comparison() -> None:
    r = cmp([True, False, True, None], [True, True, None, None])
    assert r.kind == "boolean"
    assert r.equal.tolist() == [True, False, False, True]
    r2 = cmp([True, False, True], ["yes", "0", "maybe"], type="boolean")
    assert r2.equal.tolist() == [True, True, False]
    assert r2.mismatch_type.tolist() == [None, None, "datatype"]
    assert cmp([1.0], ["true"], type="boolean").equal[0]


def test_categorical_vs_string() -> None:
    r = cmp(pd.Categorical(["a", "b"]).tolist(), ["a", "c"])
    assert r.equal.tolist() == [True, False]
