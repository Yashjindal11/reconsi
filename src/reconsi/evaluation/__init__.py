"""Ground-truth evaluation of ReconSI's detections."""

from reconsi.evaluation.framework import (
    SCENARIOS,
    Scenario,
    evaluate_result,
    run_evaluation,
    run_scenario,
    score_sets,
    summarize,
)

__all__ = [
    "SCENARIOS",
    "Scenario",
    "evaluate_result",
    "run_evaluation",
    "run_scenario",
    "score_sets",
    "summarize",
]
