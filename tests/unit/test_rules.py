from __future__ import annotations

import pandas as pd
import pytest

from reconsi import Status, reconcile
from reconsi.configuration import config_from_dict
from reconsi.core.errors import ConfigurationError
from reconsi.rules import MetricRule, Outcome, RuleSet, overall_status


@pytest.fixture
def pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    left = pd.DataFrame(
        {"id": range(100), "revenue": [100.0] * 100, "name": ["a"] * 100, "qty": [1] * 100}
    )
    right = left.copy()
    right.loc[:1, "revenue"] = 101.0  # 2 mismatches
    right = right.drop(index=[99])  # 1 missing
    return left, right


def outcomes(result: object) -> dict[str, str]:
    return {r.name: r.outcome.value for r in result.rule_results}  # type: ignore[attr-defined]


def test_default_rules_are_strict(pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(*pair, keys="id")
    o = outcomes(result)
    assert result.status == Status.FAIL
    assert o["no_missing_records"] == "fail"
    assert o["revenue_matches"] == "fail"
    assert o["name_matches"] == "pass" and o["qty_matches"] == "pass"
    assert o["no_duplicate_keys"] == "pass"


def test_thresholds_tolerate_with_warnings(pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(
        *pair,
        keys="id",
        thresholds={"max_missing_records": 5, "max_mismatch_percentage": 5},
    )
    o = outcomes(result)
    assert result.status == Status.PASS_WITH_WARNINGS
    assert o["max_missing_records"] == "warning" and o["max_mismatch_percentage"] == "warning"
    assert "revenue_matches" not in o
    tight = reconcile(*pair, keys="id", thresholds={"max_mismatch_percentage": 1})
    assert tight.status == Status.FAIL


def test_column_thresholds_and_critical(pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(
        *pair,
        keys="id",
        thresholds={"max_missing_records": 1},
        columns={"revenue": {"max_mismatch_percentage": 5}},
    )
    assert outcomes(result)["revenue_max_mismatch_percentage"] == "warning"
    assert result.status == Status.PASS_WITH_WARNINGS
    crit = reconcile(
        *pair,
        keys="id",
        columns={"revenue": {"critical": True}},
        thresholds={"max_missing_records": 1, "max_mismatch_percentage": 50},
    )
    assert outcomes(crit)["critical_revenue"] == "fail" and crit.status == Status.FAIL


def test_custom_named_rules(pair: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    result = reconcile(
        *pair,
        keys="id",
        thresholds={"max_missing_records": 1},
        rules=[
            {
                "name": "revenue_match",
                "column": "revenue",
                "type": "numeric",
                "absolute_tolerance": 1.0,
            },
            {"name": "coverage", "metric": "match_percentage", "min": 99.5, "severity": "warning"},
            {
                "name": "revenue_total",
                "metric": "column_total_difference",
                "column": "revenue",
                "max": 2,
            },
        ],
    )
    o = outcomes(result)
    assert o["revenue_match"] == "pass"  # tolerance from the rule absorbs the 1.0 difference
    assert o["coverage"] == "warning"  # 99/100 matched, below 99.5 -> warning severity
    assert o["revenue_total"] == "warning"  # total differs by 2.0: within max, so a warning
    assert result.status == Status.PASS_WITH_WARNINGS


def test_rule_not_applicable_and_validation() -> None:
    cfg = config_from_dict(
        {
            "keys": ["id"],
            "rules": [{"name": "x", "metric": "column_total_difference", "column": "name"}],
        }
    )
    rs = RuleSet.from_config(cfg, ["name"])
    assert any(isinstance(r, MetricRule) and r.name == "x" for r in rs.rules)
    with pytest.raises(ConfigurationError, match="min"):
        config_from_dict({"keys": ["id"], "rules": [{"name": "c", "metric": "match_percentage"}]})


def test_schema_and_duplicate_defaults_warn() -> None:
    left = pd.DataFrame({"id": [1, 1, 2], "v": [1, 1, 2]})
    right = pd.DataFrame({"id": [1, 1, 2], "v": [1, 1, 2], "extra": [0, 0, 0]})
    result = reconcile(left, right, keys="id", duplicate_strategy="multiset")
    o = outcomes(result)
    assert o["no_duplicate_keys"] == "warning" and o["no_schema_changes"] == "warning"
    assert result.status == Status.PASS_WITH_WARNINGS
    strict = reconcile(
        left, right, keys="id", thresholds={"max_duplicate_keys": 0, "max_schema_changes": 1}
    )
    assert outcomes(strict)["max_duplicate_keys"] == "fail"


def test_overall_status_definition() -> None:
    from reconsi.rules.engine import RuleResult

    def make(o: Outcome) -> RuleResult:
        return RuleResult("r", "m", o, "error", "rule", 0.0)

    assert overall_status([]) == Status.PASS
    assert overall_status([make(Outcome.PASS), make(Outcome.NOT_APPLICABLE)]) == Status.PASS
    assert overall_status([make(Outcome.PASS), make(Outcome.WARNING)]) == Status.PASS_WITH_WARNINGS
    assert overall_status([make(Outcome.WARNING), make(Outcome.FAIL)]) == Status.FAIL
    assert make(Outcome.FAIL).to_dict()["outcome"] == "fail"
