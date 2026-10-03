"""Both backends must produce identical reconciliation results."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reconsi import reconcile
from reconsi.backends.duckdb_backend import DuckDBBackend, q
from reconsi.core.errors import ConfigurationError
from reconsi.synthetic import generate_reconciliation_pair

pytest.importorskip("duckdb")


def _round(obj: object) -> object:
    """Round floats to 9 significant digits: summation order differs between engines."""
    if isinstance(obj, float):
        return float(f"{obj:.9g}")
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_round(v) for v in obj]
    return obj


def _comparable(result: object) -> dict[str, object]:
    r = result  # type: ignore[assignment]
    # DuckDB's CSV sniffer types date columns that pandas reads as text, so the per-column
    # "types differ" flag may legitimately differ; every count and statistic must not.
    ignored = ("left_dtype", "right_dtype", "datatype_mismatch")
    cols = {
        c: {k: v for k, v in s.to_dict().items() if k not in ignored}
        for c, s in r.columns.items()  # type: ignore[attr-defined]
    }
    return {
        "status": r.status,  # type: ignore[attr-defined]
        "summary": _round(r.summary),  # type: ignore[attr-defined]
        "columns": _round(cols),
        "missing_left": sorted(r.missing_left[r.key_columns[0]].tolist()),  # type: ignore[attr-defined]
        "missing_right": sorted(r.missing_right[r.key_columns[0]].tolist()),  # type: ignore[attr-defined]
        "mismatches": sorted(
            zip(r.value_mismatches[r.key_columns[0]], r.value_mismatches["column"], strict=True)  # type: ignore[attr-defined]
        ),
    }


@pytest.fixture(scope="module")
def pair_files(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, object]:
    pair = generate_reconciliation_pair(
        6000,
        missing_rate=0.02,
        extra_rate=0.01,
        mismatch_rate=0.01,
        duplicate_rate=0.005,
        timestamp_shift_rate=0.003,
        string_format_rate=0.003,
        seed=11,
    )
    d = tmp_path_factory.mktemp("parity")
    pair.left.to_parquet(d / "left.parquet")
    pair.right.to_csv(d / "right.csv", index=False)
    return d / "left.parquet", d / "right.csv", pair


@pytest.mark.parametrize("strategy", ["strict", "first", "last", "multiset", "aggregate"])
def test_backends_agree_on_files(pair_files: tuple[Path, Path, object], strategy: str) -> None:
    left, right, _ = pair_files
    kw = {"keys": "order_id", "duplicate_strategy": strategy, "absolute_tolerance": 0.001}
    a = reconcile(left, right, **kw)
    b = reconcile(left, right, backend="duckdb", **kw)
    assert b.metadata["backend"] == "duckdb"
    assert _comparable(a) == _comparable(b)


def test_backends_agree_on_frames_with_grain_and_mapping() -> None:
    pair = generate_reconciliation_pair(3000, mismatch_rate=0.02, seed=3)
    daily = (
        pair.right.groupby("date", as_index=False)
        .agg(revenue=("revenue", "sum"), orders=("order_id", "size"))
        .rename(columns={"date": "day"})
    )
    kw = {
        "left_group_by": ["date"],
        "right_keys": ["day"],
        "aggregations": {"revenue": "sum", "orders": "count"},
        "absolute_tolerance": 0.01,
    }
    a = reconcile(pair.left, daily, **kw)
    b = reconcile(pair.left, daily, backend="duckdb", **kw)
    assert _comparable(a) == _comparable(b)


def test_backends_agree_on_key_casting_and_normalisation() -> None:
    left = pd.DataFrame({"id": [1, 2, 3, None], "v": [1.0, 2.0, 3.0, 4.0]})
    right = pd.DataFrame({"id": [" 1", "2", "03", None], "v": [1.0, 2.5, 3.0, 4.0]})
    for kw in ({}, {"key_normalize": ["trim", "strip_leading_zeros"]}):
        a = reconcile(left, right, keys="id", **kw)
        b = reconcile(left, right, keys="id", backend="duckdb", **kw)
        assert a.summary == b.summary, kw


def test_duckdb_options_and_quoting() -> None:
    assert q('we"ird') == '"we""ird"'
    with pytest.raises(ConfigurationError, match="unknown DuckDB options"):
        DuckDBBackend({"rm -rf": 1})
    backend = DuckDBBackend({"memory_limit": "1GB", "threads": 2})
    backend.close()
    frame = pd.DataFrame({'we"ird col': [1, 2], "v": [1, 2]})
    result = reconcile(frame, frame, keys='we"ird col', backend="duckdb")
    assert result.summary["matched_records"] == 2


def test_duckdb_empty_join() -> None:
    empty = pd.DataFrame({"id": pd.Series(dtype="int64"), "v": pd.Series(dtype="float64")})
    result = reconcile(empty, empty, keys="id", backend="duckdb")
    assert result.summary["total_records"] == 0
