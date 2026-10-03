"""Known-ground-truth evaluation: does ReconSI find what was injected, and nothing else?"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from reconsi.core.reconciliation import reconcile
from reconsi.core.result import ReconciliationResult
from reconsi.synthetic.generator import GroundTruth, SyntheticPair, generate_reconciliation_pair


def score_sets(predicted: Iterable[Any], truth: Iterable[Any]) -> dict[str, float | int]:
    p, t = set(predicted), set(truth)
    tp, fp, fn = len(p & t), len(p - t), len(t - p)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


@dataclass
class Scenario:
    name: str
    description: str
    generate: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    expect_mismatch_kinds: set[str] | None = None
    """Corruption kinds that should surface as value mismatches (``None`` = all)."""
    build: Any = None
    """Optional ``(pair) -> (left, right, options)`` for scenarios that reshape the data."""


SCENARIOS: list[Scenario] = [
    Scenario("clean", "Identical datasets: nothing should be reported."),
    Scenario(
        "missing_and_extra",
        "2% of rows dropped from the right, 1% new rows added.",
        {"missing_rate": 0.02, "extra_rate": 0.01},
    ),
    Scenario(
        "value_mismatches",
        "1% of rows have a changed revenue, quantity or status.",
        {"mismatch_rate": 0.01},
    ),
    Scenario(
        "duplicates",
        "0.5% of keys duplicated on the right; reconciled with duplicate_strategy=first.",
        {"duplicate_rate": 0.005, "mismatch_rate": 0.005},
        {"duplicate_strategy": "first"},
    ),
    Scenario(
        "rounding_with_tolerance",
        "2% of revenues rounded to whole units; an absolute tolerance of 0.5 should absorb them.",
        {"rounding_rate": 0.02},
        {"absolute_tolerance": 0.5},
        expect_mismatch_kinds=set(),
    ),
    Scenario(
        "rounding_without_tolerance",
        "Same rounding with no tolerance: every rounded value must be reported.",
        {"rounding_rate": 0.02},
    ),
    Scenario(
        "timestamp_shift",
        "0.5% of updated_at values shifted by +05:30 (a timezone error).",
        {"timestamp_shift_rate": 0.005},
    ),
    Scenario(
        "string_formatting",
        "0.5% of customer names upper-cased and space-padded.",
        {"string_format_rate": 0.005},
    ),
    Scenario(
        "systematic_bias_segment",
        "Revenue 2.5% higher on the right for region West only, plus random value errors.",
        {"bias": 0.025, "bias_segment": ("region", "West"), "mismatch_rate": 0.005},
    ),
    Scenario(
        "segment_missing",
        "1% of rows missing from the right, all from channel=phone.",
        {"missing_rate": 0.01, "missing_segment": ("channel", "phone")},
    ),
    Scenario(
        "incident_window",
        "Revenue corrupted for 25% of orders on days 14-17 only.",
        {"incident_days": (14, 18), "incident_rate": 0.25},
    ),
    Scenario(
        "grain_difference",
        "Order-level left vs a daily summary on the right with one day off by 100.",
        {},
        build="grain",
    ),
]


def _build_grain(
    pair: SyntheticPair,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], set[Any]]:
    daily = pair.left.groupby("date", as_index=False).agg(
        revenue=("revenue", "sum"), orders=("order_id", "size")
    )
    bad_day = daily["date"].iloc[len(daily) // 2]
    daily.loc[daily["date"] == bad_day, "revenue"] += 100
    options = {
        "left_group_by": ["date"],
        "aggregations": {"revenue": "sum", "orders": "count"},
        "absolute_tolerance": 0.01,
    }
    return pair.left, daily, options, {(pd.Timestamp(bad_day), "revenue")}


def evaluate_result(
    result: ReconciliationResult, truth: GroundTruth, scenario: Scenario
) -> dict[str, Any]:
    key = truth.keys[0]
    out: dict[str, Any] = {}
    out["missing_from_right"] = score_sets(result.missing_right[key], truth.missing_from_right)
    out["missing_from_left"] = score_sets(result.missing_left[key], truth.missing_from_left)
    expected = truth.changed_cells(scenario.expect_mismatch_kinds)
    found = set(zip(result.value_mismatches[key], result.value_mismatches["column"], strict=True))
    out["value_mismatches"] = score_sets(found, expected)
    out["duplicate_keys"] = score_sets(result.duplicate_keys[key], truth.duplicated_keys)
    bias = result.analyses.get("bias", {}).get("revenue", {})
    out["systematic_detected"] = bool(bias.get("systematic"))
    out["systematic_expected"] = bool(truth.systematic)
    if truth.segment:
        dim, level = truth.segment
        conc = next(
            (c for c in result.analyses.get("concentration", []) if c["dimension"] == dim), None
        )
        out["segment_found"] = bool(
            conc and conc["concentrated"] and conc["top_level"]["level"] == level
        )
    if truth.missing_segment:
        dim, level = truth.missing_segment
        pop = result.analyses.get("unmatched_population", {}).get("missing_from_right", {})
        entry = next((d for d in pop.get("dimensions", []) if d["dimension"] == dim), None)
        out["missing_segment_found"] = bool(
            entry and entry["significant"] and entry["over_represented"][0]["level"] == level
        )
    if truth.incident_dates:
        start, end = (pd.Timestamp(d) for d in truth.incident_dates)
        cps = [
            pd.Timestamp(cp["period"])
            for cp in result.analyses.get("temporal", {}).get("change_points", [])
        ]
        hit_start = any(abs((cp - start).days) <= 1 for cp in cps)
        hit_end = any(abs((cp - end).days) <= 1 for cp in cps)
        out["change_points_found"] = hit_start and hit_end
        out["spurious_change_points"] = sum(
            1 for cp in cps if min(abs((cp - start).days), abs((cp - end).days)) > 1
        )
    hints = {h["kind"] for s in result.columns.values() for h in s.hints}
    if any(v == "timestamp_shift" for v in truth.value_changes.values()):
        out["timezone_hint"] = "constant_offset" in hints
    if any(v == "string_format" for v in truth.value_changes.values()):
        out["formatting_hint"] = "string_normalization" in hints
    out["status"] = result.status.value
    return out


def run_scenario(scenario: Scenario, rows: int, seed: int) -> dict[str, Any]:
    pair = generate_reconciliation_pair(rows, seed=seed, **scenario.generate)
    t0 = time.perf_counter()
    if scenario.build == "grain":
        left, right, options, truth_cells = _build_grain(pair)
        result = reconcile(left, right, **options)
        found = set(
            zip(result.value_mismatches["date"], result.value_mismatches["column"], strict=True)
        )
        metrics: dict[str, Any] = {
            "value_mismatches": score_sets({(pd.Timestamp(d), c) for d, c in found}, truth_cells),
            "status": result.status.value,
        }
        naive = reconcile(left, right, keys="date", compare_columns=["revenue"])
        diag = naive.analyses.get("aggregation_diagnosis", {})
        metrics["naive_value_mismatch_records"] = naive.summary["value_mismatch_records"]
        metrics["naive_ambiguous_records"] = naive.summary["ambiguous_records"]
        metrics["grain_diagnosed"] = bool(diag) and not diag.get("explained_by_grain", True)
    else:
        result = reconcile(pair.left, pair.right, keys="order_id", **scenario.options)
        metrics = evaluate_result(result, pair.truth, scenario)
    metrics["seconds"] = time.perf_counter() - t0
    return {"scenario": scenario.name, "seed": seed, "rows": rows, **metrics}


def run_evaluation(
    rows: int = 20_000, seeds: Iterable[int] = (0, 1, 2), scenarios: Iterable[Scenario] = SCENARIOS
) -> list[dict[str, Any]]:
    return [run_scenario(s, rows, seed) for s in scenarios for seed in seeds]


def summarize(runs: list[dict[str, Any]]) -> pd.DataFrame:
    """One row per scenario: mean F1/recall of set detections and rate of boolean detections."""
    rows = []
    for name, group in pd.DataFrame(runs).groupby("scenario", sort=False):
        row: dict[str, Any] = {"scenario": name, "runs": len(group)}
        for metric in (
            "missing_from_right",
            "missing_from_left",
            "value_mismatches",
            "duplicate_keys",
        ):
            if metric in group and group[metric].notna().all():
                scores = group[metric].tolist()
                row[f"{metric}_precision"] = float(np.mean([s["precision"] for s in scores]))
                row[f"{metric}_recall"] = float(np.mean([s["recall"] for s in scores]))
        for flag in (
            "systematic_detected",
            "segment_found",
            "missing_segment_found",
            "change_points_found",
            "timezone_hint",
            "formatting_hint",
            "grain_diagnosed",
        ):
            if flag in group and group[flag].notna().any():
                row[flag] = float(group[flag].dropna().astype(bool).mean())
        if "spurious_change_points" in group:
            row["spurious_change_points"] = float(group["spurious_change_points"].dropna().mean())
        row["statuses"] = ", ".join(sorted(set(group["status"])))
        row["mean_seconds"] = float(group["seconds"].mean())
        rows.append(row)
    return pd.DataFrame(rows)
