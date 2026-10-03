"""Stable dataset fingerprints that reveal whether an input changed between runs.

File fingerprints stream the file through SHA-256 in fixed-size chunks (constant memory). Files
larger than ``full_hash_limit`` bytes are fingerprinted from their size, modification time,
first and last megabyte and (for Parquet) footer metadata instead of a full read.
In-memory frames are fingerprinted from their schema, row count and a deterministic row sample.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from reconsi.inputs.sources import TableSource

CHUNK = 1 << 20
FULL_HASH_LIMIT = 512 * (1 << 20)


def _digest(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def fingerprint_file(
    path: str | Path, *, file_format: str | None = None, full_hash_limit: int = FULL_HASH_LIMIT
) -> dict[str, Any]:
    p = Path(path)
    stat = p.stat()
    out: dict[str, Any] = {
        "kind": "file",
        "path": str(p),
        "format": file_format,
        "size_bytes": stat.st_size,
        "modified": pd.Timestamp(stat.st_mtime, unit="s", tz="UTC").isoformat(),
    }
    h = hashlib.sha256()
    with p.open("rb") as fh:
        if stat.st_size <= full_hash_limit:
            out["method"] = "sha256"
            while chunk := fh.read(CHUNK):
                h.update(chunk)
        else:
            out["method"] = "sampled"
            h.update(fh.read(CHUNK))
            fh.seek(max(0, stat.st_size - CHUNK))
            h.update(fh.read(CHUNK))
            h.update(str(stat.st_size).encode())
    out["content_hash"] = h.hexdigest()
    if file_format == "parquet":
        try:
            import pyarrow.parquet as pq

            meta = pq.read_metadata(p)
            out["row_count"] = int(meta.num_rows)
            out["columns"] = [str(meta.schema.column(i).name) for i in range(meta.num_columns)]
        except Exception as exc:  # pragma: no cover - metadata is optional
            out["metadata_error"] = str(exc)
    # mtime is informative but excluded from the digest so identical copies match.
    out["digest"] = _digest({k: v for k, v in out.items() if k not in ("modified", "path")})
    return out


def fingerprint_frame(frame: pd.DataFrame, *, sample_rows: int = 2000) -> dict[str, Any]:
    n = len(frame)
    if n > sample_rows:
        positions = np.unique(np.linspace(0, n - 1, sample_rows).astype(int))
        sample = frame.iloc[positions]
    else:
        sample = frame
    try:
        hashed = pd.util.hash_pandas_object(sample, index=False).to_numpy()
        sample_hash = hashlib.sha256(hashed.tobytes()).hexdigest()
    except TypeError:  # unhashable cells (lists, dicts)
        sample_hash = hashlib.sha256(sample.astype(str).to_csv(index=False).encode()).hexdigest()
    out: dict[str, Any] = {
        "kind": "dataframe",
        "row_count": n,
        "columns": [str(c) for c in frame.columns],
        "dtypes": [str(t) for t in frame.dtypes],
        "sample_rows": len(sample),
        "sample_hash": sample_hash,
    }
    out["digest"] = _digest(out)
    return out


def fingerprint_source(source: TableSource) -> dict[str, Any]:
    if source.path is not None:
        return fingerprint_file(source.path, file_format=source.format)
    assert source.frame is not None
    return fingerprint_frame(source.frame)
