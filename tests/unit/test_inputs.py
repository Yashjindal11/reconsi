from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from reconsi.core.errors import InputError
from reconsi.inputs import as_source, load_table


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame({"id": ["001", "002", "010"], "amount": [1.5, 2.0, 3.25]})


def test_dataframe_passthrough(frame: pd.DataFrame) -> None:
    src = as_source(frame, "left")
    assert src.to_pandas() is frame
    assert src.describe()["kind"] == "dataframe"


def test_csv_keeps_leading_zeros_for_string_columns(tmp_path: Path, frame: pd.DataFrame) -> None:
    path = tmp_path / "a.csv"
    frame.to_csv(path, index=False)
    assert load_table(path)["id"].tolist() == [1, 2, 10]
    src = as_source(path, "a")
    assert src.to_pandas(string_columns=["id"])["id"].tolist() == ["001", "002", "010"]


def test_tsv_separator_detected(tmp_path: Path, frame: pd.DataFrame) -> None:
    path = tmp_path / "a.tsv"
    frame.to_csv(path, index=False, sep="\t")
    assert list(load_table(path).columns) == ["id", "amount"]


def test_parquet_roundtrip(tmp_path: Path, frame: pd.DataFrame) -> None:
    path = tmp_path / "a.parquet"
    frame.to_parquet(path)
    out = load_table(path)
    assert out["id"].tolist() == ["001", "002", "010"]


def test_json_and_jsonl(tmp_path: Path, frame: pd.DataFrame) -> None:
    p1 = tmp_path / "a.json"
    p1.write_text(json.dumps(frame.to_dict(orient="records")))
    assert as_source(p1, "a").to_pandas(string_columns=["id"])["id"].tolist() == [
        "001",
        "002",
        "010",
    ]
    p2 = tmp_path / "a.jsonl"
    frame.to_json(p2, orient="records", lines=True)
    assert len(load_table(p2)) == 3


def test_relative_path_resolved_against_base_dir(tmp_path: Path, frame: pd.DataFrame) -> None:
    (tmp_path / "data").mkdir()
    frame.to_csv(tmp_path / "data" / "x.csv", index=False)
    src = as_source("data/x.csv", "x", base_dir=tmp_path)
    assert src.path == (tmp_path / "data" / "x.csv").resolve()


def test_rejects_urls_missing_files_and_directories(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="local files"):
        as_source("https://example.com/a.csv", "a")
    with pytest.raises(InputError, match="not found"):
        as_source(tmp_path / "nope.csv", "a")
    with pytest.raises(InputError, match="not a file"):
        as_source(tmp_path, "a")


def test_unknown_format_and_disallowed_options(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_text("x")
    with pytest.raises(InputError, match="format"):
        as_source(path, "a")
    csv = tmp_path / "a.csv"
    csv.write_text("a\n1\n")
    with pytest.raises(InputError, match="not allowed"):
        as_source(csv, "a", read_options={"storage_options": {}})
    assert as_source(csv, "a", read_options={"sep": ","}).to_pandas()["a"].tolist() == [1]


def test_to_pandas_adapter_objects(frame: pd.DataFrame) -> None:
    import pyarrow as pa

    table = pa.Table.from_pandas(frame, preserve_index=False)
    assert as_source(table, "t").to_pandas()["amount"].sum() == pytest.approx(6.75)


def test_unsupported_object() -> None:
    with pytest.raises(InputError, match="Unsupported input type"):
        as_source(42, "x")


def test_unreadable_file_raises_input_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.parquet"
    path.write_text("not parquet")
    with pytest.raises(InputError, match="Could not read"):
        load_table(path)
