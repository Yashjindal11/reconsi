from __future__ import annotations

import datetime as dt
import json
import math
from decimal import Decimal
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from reconsi.core.dtypes import compatible_types, logical_type, type_family
from reconsi.core.serialization import frame_records, to_jsonable


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1, 2, 3], "integer"),
        ([1.0, None], "float"),
        ([True, False], "boolean"),
        (["a", None], "string"),
        (pd.to_datetime(["2026-01-01"]), "datetime"),
        (pd.to_datetime(["2026-01-01"]).tz_localize("UTC"), "datetime_tz"),
        ([dt.date(2026, 1, 1)], "date"),
        ([None, None], "empty"),
        ([1, "a"], "mixed"),
        ([pd.Timedelta(1, "s")], "timedelta"),
    ],
)
def test_logical_type(values: object, expected: str) -> None:
    series = (
        pd.Series(values, dtype=object)
        if expected in {"empty", "mixed", "date"}
        else pd.Series(values)
    )
    assert logical_type(series) == expected


def test_categorical_and_object_tz() -> None:
    assert logical_type(pd.Series(["a", "b"], dtype="category")) == "categorical"
    ts = pd.Timestamp("2026-01-01", tz="UTC").to_pydatetime()
    assert logical_type(pd.Series([ts], dtype=object)) == "datetime_tz"


def test_type_compatibility() -> None:
    assert type_family("integer") == type_family("float") == "numeric"
    assert compatible_types("integer", "float")
    assert compatible_types("string", "categorical")
    assert compatible_types("date", "datetime")
    assert not compatible_types("datetime", "datetime_tz")
    assert not compatible_types("integer", "string")
    assert compatible_types("empty", "string")


class Color(Enum):
    RED = "red"


def test_to_jsonable_is_strict_json() -> None:
    payload = {
        "nan": float("nan"),
        "inf": np.float64("inf"),
        "i": np.int64(3),
        "b": np.bool_(True),
        "ts": pd.Timestamp("2026-10-03T10:00:00Z"),
        "nat": pd.NaT,
        "na": pd.NA,
        "d": dt.date(2026, 1, 2),
        "td": pd.Timedelta(90, "s"),
        "dec": Decimal("1.5"),
        "path": Path("/tmp/x"),
        "enum": Color.RED,
        "arr": np.array([1.0, np.nan]),
        "tuple": (1, 2),
        "obj": object,
    }
    out = to_jsonable(payload)
    json.dumps(out, allow_nan=False)
    assert out["nan"] is None and out["inf"] is None and out["nat"] is None
    assert out["ts"].startswith("2026-10-03T10:00:00")
    assert out["td"] == 90.0 and out["arr"] == [1.0, None] and out["enum"] == "red"
    assert math.isclose(out["dec"], 1.5)


def test_frame_records_limit() -> None:
    frame = pd.DataFrame({"a": [1, 2, 3], "b": [None, "x", "y"]})
    assert frame_records(frame, limit=2) == [{"a": 1, "b": None}, {"a": 2, "b": "x"}]
