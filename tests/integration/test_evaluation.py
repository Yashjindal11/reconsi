"""Known-ground-truth scenarios: ReconSI must find exactly what was injected."""

from __future__ import annotations

import pytest

from reconsi.evaluation import SCENARIOS, run_scenario, score_sets, summarize

pytestmark = pytest.mark.integration

BY_NAME = {s.name: s for s in SCENARIOS}


def test_score_sets() -> None:
    s = score_sets({1, 2, 3}, {2, 3, 4})
    assert (s["tp"], s["fp"], s["fn"]) == (2, 1, 1)
    assert s["precision"] == pytest.approx(2 / 3)
    assert score_sets([], [])["f1"] == 1.0


@pytest.fixture(scope="module")
def runs() -> dict[str, dict[str, object]]:
    return {s.name: run_scenario(s, rows=6000, seed=0) for s in SCENARIOS}


def _perfect(score: object) -> bool:
    return score["precision"] == 1.0 and score["recall"] == 1.0  # type: ignore[index]


def test_clean_is_silent(runs: dict[str, dict[str, object]]) -> None:
    r = runs["clean"]
    assert r["status"] == "PASS" and not r["systematic_detected"]


@pytest.mark.parametrize(
    "name",
    [
        "missing_and_extra",
        "value_mismatches",
        "duplicates",
        "rounding_with_tolerance",
        "rounding_without_tolerance",
        "timestamp_shift",
        "string_formatting",
        "segment_missing",
    ],
)
def test_record_level_detection_is_exact(runs: dict[str, dict[str, object]], name: str) -> None:
    r = runs[name]
    for metric in ("missing_from_right", "missing_from_left", "value_mismatches", "duplicate_keys"):
        assert _perfect(r[metric]), (name, metric, r[metric])


def test_diagnostics(runs: dict[str, dict[str, object]]) -> None:
    assert runs["timestamp_shift"]["timezone_hint"]
    assert runs["string_formatting"]["formatting_hint"]
    assert runs["systematic_bias_segment"]["systematic_detected"]
    assert runs["systematic_bias_segment"]["segment_found"]
    assert not runs["value_mismatches"]["systematic_detected"]
    assert runs["segment_missing"]["missing_segment_found"]
    assert runs["incident_window"]["change_points_found"]
    assert runs["incident_window"]["spurious_change_points"] == 0
    g = runs["grain_difference"]
    assert _perfect(g["value_mismatches"]) and g["grain_diagnosed"]


def test_summary_table(runs: dict[str, dict[str, object]]) -> None:
    table = summarize(list(runs.values()))
    assert len(table) == len(SCENARIOS)
    assert "value_mismatches_recall" in table.columns
