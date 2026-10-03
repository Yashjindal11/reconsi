from __future__ import annotations

import numpy as np
import pandas as pd

from reconsi import reconcile
from reconsi.aggregation import aggregate_frame
from reconsi.aggregation.diagnosis import aggregation_diagnosis
from reconsi.aggregation.grain import compare_grains, infer_grain


def _sales(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    txn = 0
    for d in ["2026-10-01", "2026-10-02", "2026-10-03"]:
        for store in ["S1", "S2"]:
            for product in ["P1", "P2", "P3"]:
                for _ in range(2):
                    txn += 1
                    rows.append((f"T{txn:04d}", d, store, product, float(rng.integers(1, 100))))
    return pd.DataFrame(rows, columns=["txn_id", "date", "store", "product", "revenue"])


def test_infer_grain_single_unique_column() -> None:
    g = infer_grain(_sales())
    assert g.columns == ["txn_id"]
    assert g.to_dict()["label"] == "inference"


def test_infer_grain_composite() -> None:
    daily = aggregate_frame(_sales(), ["date", "store", "product"], {"revenue": "sum"})
    g = infer_grain(daily)
    assert g.columns == ["date", "store", "product"]
    store_day = aggregate_frame(_sales(), ["date", "store"], {"revenue": "sum"})
    assert infer_grain(store_day).columns == ["date", "store"]
    rel = compare_grains(infer_grain(daily, side="left"), infer_grain(store_day, side="right"))
    assert rel["relationship"] == "left_finer"


def test_infer_grain_none_and_verify_rejection() -> None:
    frame = pd.DataFrame({"a": [1, 1, 2, 2], "v": [1.0, 2.0, 3.0, 4.0]})
    g = infer_grain(frame)
    assert g.columns is None and "no unique" in g.description
    g = infer_grain(pd.DataFrame({"a": [1, 2]}), verify=lambda cols: False)
    assert g.columns is None


def test_aggregate_frame_count_and_size() -> None:
    frame = pd.DataFrame({"d": ["x", "x", "y"], "v": [1.0, None, 3.0]})
    out = aggregate_frame(frame, ["d"], {"v": "count", "orders": "count", "n": "size"})
    assert out.to_dict(orient="list") == {
        "d": ["x", "y"],
        "v": [1, 1],
        "orders": [2, 1],
        "n": [2, 1],
    }


def test_aggregation_diagnosis_explains_grain() -> None:
    sales = _sales()
    daily = aggregate_frame(sales, ["date"], {"revenue": "sum"})
    diag = aggregation_diagnosis(sales, daily, ["date"], ["revenue"])
    assert diag is not None and diag["explained_by_grain"]
    assert diag["columns"]["revenue"]["share_matching"] == 1.0
    daily.loc[0, "revenue"] += 10
    diag = aggregation_diagnosis(sales, daily, ["date"], ["revenue"])
    assert diag is not None and not diag["explained_by_grain"]
    assert diag["columns"]["revenue"]["difference"] == 10.0


def test_engine_reports_grain_control_totals_and_diagnosis() -> None:
    sales = _sales()
    daily = aggregate_frame(sales, ["date"], {"revenue": "sum"})
    result = reconcile(sales, daily, keys="date", compare_columns=["revenue"])
    grain = result.analyses["grain"]
    assert grain["left"]["columns"] == ["txn_id"] and grain["right"]["columns"] == ["date"]
    assert grain["keys_are_grain"] == {"left": False, "right": True}
    diag = result.analyses["aggregation_diagnosis"]
    assert diag["explained_by_grain"]
    totals = result.analyses["control_totals"]
    assert totals["columns"]["revenue"]["difference"] == 0.0
    assert totals["rows"] == {"left": 36, "right": 3, "difference": -33}


def test_no_diagnosis_when_keys_unique() -> None:
    frame = pd.DataFrame({"id": [1, 2], "v": [1.0, 2.0]})
    assert "aggregation_diagnosis" not in reconcile(frame, frame, keys="id").analyses
