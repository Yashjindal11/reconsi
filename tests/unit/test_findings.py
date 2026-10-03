from __future__ import annotations

import json

import numpy as np
import pandas as pd

from reconsi import Evidence, Severity, reconcile
from reconsi.aggregation import aggregate_frame


def titles(result: object) -> list[str]:
    return [f.title for f in result.findings]  # type: ignore[attr-defined]


def by_category(result: object, category: str) -> list[object]:
    return [f for f in result.findings if f.category == category]  # type: ignore[attr-defined]


def test_findings_are_ranked_and_labelled() -> None:
    left = pd.DataFrame({"id": [1, 2, 3], "v": [1.0, 2.0, 3.0]})
    right = pd.DataFrame({"id": [1, 2, 4], "v": [1.0, 2.5, 4.0]})
    result = reconcile(left, right, keys="id")
    severities = [f.severity for f in result.findings]
    order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    assert severities == sorted(severities, key=order.__getitem__)
    assert result.findings[0].evidence == Evidence.RULE
    assert any("missing from the right" in t for t in titles(result))
    doc = result.to_dict()
    json.dumps(doc, allow_nan=False)
    assert {f["evidence"] for f in doc["findings"]} <= {e.value for e in Evidence}
    assert doc["recommendations"]


def test_many_to_many_and_inflation_finding() -> None:
    left = pd.DataFrame({"id": [1, 1, 2, 2], "v": [1, 2, 3, 4]})
    right = pd.DataFrame({"id": [1, 1, 1, 2], "v": [1, 2, 3, 4]})
    result = reconcile(left, right, keys="id")
    risk = [f for f in result.findings if f.title == "Many-to-many reconciliation risk"]
    assert risk and risk[0].severity == Severity.CRITICAL
    assert "would produce 8 rows" in risk[0].detail


def test_key_format_and_normalisation_findings() -> None:
    left = pd.DataFrame({"id": [f"{i:05d}" for i in range(1, 30)], "v": 1})
    right = pd.DataFrame({"id": [str(i) for i in range(1, 30)], "v": 1})
    result = reconcile(left, right, keys="id")
    likely = [f for f in by_category(result, "keys") if f.evidence == Evidence.LIKELY]  # type: ignore[attr-defined]
    assert likely and "strip_leading_zeros" in likely[0].title  # type: ignore[attr-defined]
    assert "key_normalize" in likely[0].recommendation  # type: ignore[attr-defined]


def test_string_and_timezone_hint_findings() -> None:
    left = pd.DataFrame(
        {
            "id": range(20),
            "name": ["Acme"] * 20,
            "ts": pd.date_range("2026-01-01", periods=20, freq="h"),
        }
    )
    right = left.assign(name=" ACME", ts=left["ts"] + pd.Timedelta(hours=5, minutes=30))
    result = reconcile(left, right, keys="id")
    t = titles(result)
    assert any("formatting only" in x for x in t)
    assert any("constant +05:30" in x for x in t)


def test_grain_finding() -> None:
    rng = np.random.default_rng(0)
    tx = pd.DataFrame(
        {
            "txn": range(60),
            "date": np.repeat(["2026-01-01", "2026-01-02", "2026-01-03"], 20),
            "rev": rng.integers(1, 9, 60),
        }
    )
    daily = aggregate_frame(tx, ["date"], {"rev": "sum"})
    result = reconcile(tx, daily, keys="date", compare_columns=["rev"])
    grain = by_category(result, "grain")
    assert any("explained by grain" in g.title for g in grain)  # type: ignore[attr-defined]


def test_schema_suggestion_finding() -> None:
    left = pd.DataFrame({"id": [1, 2], "sales_amount": [1.0, 2.0]})
    right = pd.DataFrame({"id": [1, 2], "sales_amt": [1.0, 2.0]})
    result = reconcile(left, right, keys="id")
    sugg = [f for f in by_category(result, "schema") if "Suggested" in f.title]  # type: ignore[attr-defined]
    assert sugg and sugg[0].evidence == Evidence.LIKELY  # type: ignore[attr-defined]
    assert "Not applied" in sugg[0].detail  # type: ignore[attr-defined]
