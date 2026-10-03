from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reconsi import reconcile
from reconsi.configuration import ReconConfig
from reconsi.core.errors import ReconsiError
from reconsi.core.reproducibility import config_hash, git_state, new_run_id
from reconsi.fingerprints import fingerprint_file, fingerprint_frame
from reconsi.history import HistoryStore
from reconsi.reports.diff import diff_documents, render_diff


def test_frame_fingerprint_stable_and_sensitive() -> None:
    a = pd.DataFrame({"id": range(5000), "v": range(5000)})
    assert fingerprint_frame(a)["digest"] == fingerprint_frame(a.copy())["digest"]
    b = a.copy()
    b.loc[0, "v"] = -1
    assert fingerprint_frame(a)["digest"] != fingerprint_frame(b)["digest"]
    assert fingerprint_frame(a)["sample_rows"] == 2000


def test_file_fingerprint_full_and_sampled(tmp_path: Path) -> None:
    p = tmp_path / "a.csv"
    p.write_bytes(b"id,v\n1,2\n")
    full = fingerprint_file(p, file_format="csv")
    assert full["method"] == "sha256" and full["size_bytes"] == 9
    copy = tmp_path / "b.csv"
    copy.write_bytes(b"id,v\n1,2\n")
    assert fingerprint_file(copy, file_format="csv")["digest"] == full["digest"]
    sampled = fingerprint_file(p, full_hash_limit=1)
    assert sampled["method"] == "sampled"


def test_parquet_fingerprint_reads_metadata_only(tmp_path: Path) -> None:
    p = tmp_path / "a.parquet"
    pd.DataFrame({"id": [1, 2, 3]}).to_parquet(p)
    fp = fingerprint_file(p, file_format="parquet")
    assert fp["row_count"] == 3 and fp["columns"] == ["id"]


def test_reproducibility_helpers(tmp_path: Path) -> None:
    assert config_hash(ReconConfig(keys=["a"])) == config_hash(ReconConfig(keys=["a"]))
    assert config_hash(ReconConfig(keys=["a"])) != config_hash(ReconConfig(keys=["b"]))
    assert new_run_id() != new_run_id()
    assert git_state(tmp_path) == {"git_commit": None, "git_dirty": None}


def test_result_metadata_records_reproducibility() -> None:
    frame = pd.DataFrame({"id": [1], "v": [1]})
    meta = reconcile(frame, frame, keys="id", seed=7).metadata
    for key in ("run_id", "reconsi_version", "python_version", "packages", "config_hash", "seed"):
        assert meta[key] is not None
    assert meta["left_fingerprint"]["digest"] == meta["right_fingerprint"]["digest"]


def test_history_store_and_diff(tmp_path: Path) -> None:
    db = tmp_path / "h" / "history.db"
    left = pd.DataFrame({"id": [1, 2, 3], "v": [1, 2, 3]})
    first = reconcile(left, left, keys="id", name="daily", history={"path": str(db)})
    second = reconcile(
        left, left.assign(v=[1, 2, 4]), keys="id", name="daily", history={"path": str(db)}
    )
    store = HistoryStore(db)
    runs = store.runs("daily")
    assert list(runs["run_id"]) == [second.metadata["run_id"], first.metadata["run_id"]]
    assert list(runs["status"]) == ["FAIL", "PASS"]
    doc = store.get(first.metadata["run_id"])
    assert doc["status"] == "PASS"
    prev = store.previous("daily", second.metadata["started_at"])
    assert prev is not None and prev["metadata"]["run_id"] == first.metadata["run_id"]
    diff = diff_documents(first.to_dict(), second.to_dict())
    assert diff["status_changed"] and diff["inputs"]["right"]["changed"]
    assert not diff["inputs"]["left"]["changed"]
    assert diff["columns"] == [{"column": "v", "before": 0, "after": 1}]
    text = render_diff(diff)
    assert "PASS -> FAIL" in text and "value_mismatch_records" in text
    with pytest.raises(ReconsiError, match="no run"):
        store.get("missing")


def test_history_disabled(tmp_path: Path) -> None:
    frame = pd.DataFrame({"id": [1], "v": [1]})
    reconcile(frame, frame, keys="id", history={"enabled": False, "path": str(tmp_path / "x.db")})
    assert not (tmp_path / "x.db").exists()
