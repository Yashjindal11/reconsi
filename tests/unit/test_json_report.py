from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from reconsi import reconcile
from reconsi.core.errors import ReconsiError
from reconsi.reports.json_report import load_document, validate_document


@pytest.fixture
def result() -> object:
    left = pd.DataFrame(
        {
            "id": [1, 1, 2, 3, 5],
            "name": ["a", "a", "b", "c", "e"],
            "v": [1.0, 1.0, 2.0, 3.0, 5.0],
            "ts": pd.to_datetime(["2026-01-01"] * 5),
        }
    )
    right = pd.DataFrame(
        {
            "id": [1, 2, 4, 5],
            "name": ["a", "B", "d", "e"],
            "v": [1.0, 2.5, 4.0, 5.0],
            "ts": pd.to_datetime(["2026-01-01"] * 4),
        }
    )
    return reconcile(left, right, keys="id")


def test_document_round_trip_and_validation(result: object, tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    result.to_json(path)  # type: ignore[attr-defined]
    doc = load_document(path)
    assert validate_document(doc) == []
    assert doc["schema_version"] == "1.0"
    assert doc["records"]["value_mismatch_sample"][0]["column"] in {"name", "v"}
    assert doc["configuration"]["keys"] == ["id"]


def test_document_is_strict_json(result: object) -> None:
    text = result.to_json()  # type: ignore[attr-defined]
    assert "NaN" not in text and "Infinity" not in text
    json.loads(text)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.pop("summary"), "missing field 'summary'"),
        (lambda d: d.update(status="MAYBE"), "status must be"),
        (lambda d: d.update(schema_version="9"), "unsupported schema_version"),
        (lambda d: d["summary"].pop("matched_records"), "summary is missing"),
        (lambda d: d.update(rules={}), "wrong type"),
    ],
)
def test_validation_errors(result: object, mutate: object, message: str) -> None:
    doc = result.to_dict()  # type: ignore[attr-defined]
    mutate(doc)  # type: ignore[operator]
    assert any(message in e for e in validate_document(doc))


def test_load_document_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ReconsiError, match="could not read"):
        load_document(bad)
    bad.write_text("[]")
    with pytest.raises(ReconsiError, match="not a valid"):
        load_document(bad)


def test_export_csv_parquet_json(result: object, tmp_path: Path) -> None:
    files = result.export(tmp_path / "evidence", formats=["csv", "parquet", "json"])  # type: ignore[attr-defined]
    assert {
        "missing_left.csv",
        "missing_right.parquet",
        "value_mismatches.json",
        "result.json",
    } <= set(files)
    assert pd.read_csv(files["missing_left.csv"])["id"].tolist() == [4]
    assert pd.read_csv(files["missing_right.csv"])["id"].tolist() == [3]
    mism = pd.read_parquet(files["value_mismatches.parquet"])
    assert set(mism["column"]) == {"name", "v"}
    dups = pd.read_csv(files["duplicate_keys.csv"])
    assert dups.to_dict(orient="records") == [{"id": 1, "left_count": 2, "right_count": 1}]
    assert len(pd.read_csv(files["records.csv"])) == 4


def test_export_rejects_unknown_format(result: object, tmp_path: Path) -> None:
    with pytest.raises(ReconsiError, match="unsupported export formats"):
        result.export(tmp_path, formats=["xlsx"])  # type: ignore[attr-defined]
