"""Convert analysis objects into strict JSON-compatible values."""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from collections.abc import Mapping
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def to_jsonable(value: Any) -> Any:
    """Recursively convert ``value`` to types accepted by ``json.dumps(allow_nan=False)``.

    NaN and infinities become ``None``; timestamps become ISO-8601 strings.
    """
    if value is None or isinstance(value, bool | str):
        return value
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, pd.Timedelta | dt.timedelta):
        return pd.Timedelta(value).total_seconds()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "to_dict"):
            return to_jsonable(value.to_dict())
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if hasattr(value, "model_dump"):
        return to_jsonable(value.model_dump(mode="json"))
    if isinstance(value, pd.DataFrame):
        return frame_records(value)
    if isinstance(value, pd.Series):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def json_dict(value: Any) -> dict[str, Any]:
    """``to_jsonable`` for values known to serialise to a JSON object."""
    out = to_jsonable(value)
    assert isinstance(out, dict)
    return out


def frame_records(frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    """Return ``frame`` as a list of JSON-safe row dictionaries."""
    if limit is not None:
        frame = frame.head(limit)
    columns = [str(c) for c in frame.columns]
    out: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False, name=None):
        out.append({c: to_jsonable(v) for c, v in zip(columns, row, strict=True)})
    return out


def scalar(value: Any) -> Any:
    """Convert a single pandas/numpy scalar to a plain Python value (keeps NaN as None)."""
    return to_jsonable(value)
