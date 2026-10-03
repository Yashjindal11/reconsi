"""Rules, rule sets and the overall reconciliation status.

Status definition (also in ``docs/rules.md``):

* ``FAIL`` - at least one rule failed. Rules with severity ``error`` fail when their observed
  value breaks the threshold.
* ``PASS_WITH_WARNINGS`` - no rule failed, but at least one produced a warning: either a
  ``warning``-severity rule broke its threshold, or differences exist that are within a
  configured (non-zero) threshold.
* ``PASS`` - every applicable rule passed with nothing to report.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from reconsi.comparison.records import ColumnStatistics
from reconsi.configuration.models import ReconConfig
from reconsi.core.types import Status
from reconsi.schema.compare import SchemaDiff

PERCENT_METRICS = frozenset(
    {
        "missing_percentage",
        "mismatch_percentage",
        "match_percentage",
        "column_mismatch_percentage",
        "column_total_relative_difference",
    }
)


class Outcome(StrEnum):
    PASS = "pass"  # noqa: S105
    WARNING = "warning"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class RuleContext:
    summary: dict[str, Any]
    columns: dict[str, ColumnStatistics]
    schema: SchemaDiff


@dataclass(frozen=True)
class RuleResult:
    name: str
    metric: str
    outcome: Outcome
    severity: str
    source: str
    observed: float | None
    max: float | None = None
    min: float | None = None
    column: str | None = None
    message: str = ""
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metric": self.metric,
            "column": self.column,
            "outcome": self.outcome.value,
            "severity": self.severity,
            "source": self.source,
            "observed": self.observed,
            "max": self.max,
            "min": self.min,
            "message": self.message,
            "description": self.description,
        }


class Rule(ABC):
    name: str
    severity: str

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleResult: ...


def metric_value(context: RuleContext, metric: str, column: str | None = None) -> float | None:
    s = context.summary
    simple = {
        "missing_records": s["missing_records"],
        "missing_left_records": s["missing_left"],
        "missing_right_records": s["missing_right"],
        "missing_percentage": s["missing_percentage"],
        "mismatched_records": s["value_mismatch_records"],
        "mismatch_percentage": s["mismatch_percentage"],
        "match_percentage": s["match_percentage"],
        "duplicate_keys": s["duplicate_keys_left"] + s["duplicate_keys_right"],
        "ambiguous_records": s["ambiguous_records"],
        "schema_changes": context.schema.change_count,
    }
    if metric in simple:
        return float(simple[metric])
    if column is None or column not in context.columns:
        return None
    stats = context.columns[column]
    if metric == "column_mismatches":
        return float(stats.mismatches)
    if metric == "column_mismatch_percentage":
        return 100.0 * stats.mismatch_rate
    if stats.totals is None:
        return None
    if metric == "column_total_difference":
        return abs(float(stats.totals["difference"] or 0.0))
    if metric == "column_total_relative_difference":
        rel = stats.totals.get("relative_difference")
        return None if rel is None else 100.0 * abs(float(rel))
    return None


def _fmt(metric: str, value: float | None) -> str:
    if value is None:
        return "n/a"
    if metric in PERCENT_METRICS:
        return f"{value:.4g}%"
    return f"{value:,.6g}"


@dataclass
class MetricRule(Rule):
    name: str
    metric: str
    max: float | None = None
    min: float | None = None
    column: str | None = None
    severity: str = "error"
    source: str = "rule"
    description: str | None = None

    def evaluate(self, context: RuleContext) -> RuleResult:
        observed = metric_value(context, self.metric, self.column)
        base: dict[str, Any] = {
            "name": self.name,
            "metric": self.metric,
            "severity": self.severity,
            "source": self.source,
            "observed": observed,
            "max": self.max,
            "min": self.min,
            "column": self.column,
            "description": self.description,
        }
        if observed is None:
            return RuleResult(
                outcome=Outcome.NOT_APPLICABLE, message="metric not available", **base
            )
        what = f"{self.metric}{f' [{self.column}]' if self.column else ''}"
        broken = (self.max is not None and observed > self.max) or (
            self.min is not None and observed < self.min
        )
        if broken:
            outcome = Outcome.FAIL if self.severity == "error" else Outcome.WARNING
            limit = (
                f"max {_fmt(self.metric, self.max)}"
                if self.max is not None and observed > self.max
                else f"min {_fmt(self.metric, self.min)}"
            )
            return RuleResult(
                outcome=outcome,
                message=f"{what} = {_fmt(self.metric, observed)} breaks {limit}",
                **base,
            )
        tolerated = (self.max is not None and observed > 0) or (
            self.min is not None and self.metric == "match_percentage" and observed < 100
        )
        if tolerated:
            return RuleResult(
                outcome=Outcome.WARNING,
                message=f"{what} = {_fmt(self.metric, observed)} is within the configured threshold",
                **base,
            )
        return RuleResult(
            outcome=Outcome.PASS, message=f"{what} = {_fmt(self.metric, observed)}", **base
        )


@dataclass
class RuleSet:
    rules: list[Rule] = field(default_factory=list)

    def add(self, rule: Rule) -> None:
        self.rules.append(rule)

    def evaluate(self, context: RuleContext) -> list[RuleResult]:
        return [r.evaluate(context) for r in self.rules]

    @classmethod
    def from_config(cls, cfg: ReconConfig, compare_columns: list[str]) -> RuleSet:
        """Build defaults, threshold rules, column rules and named custom rules."""
        rs = cls()
        t = cfg.thresholds
        if t.max_missing_records is None and t.max_missing_percentage is None:
            rs.add(MetricRule("no_missing_records", "missing_records", max=0, source="default"))
        # Records set aside as ambiguous were never compared, so they cannot count as reconciled.
        rs.add(MetricRule("no_ambiguous_records", "ambiguous_records", max=0, source="default"))
        if t.max_missing_records is not None:
            rs.add(
                MetricRule(
                    "max_missing_records",
                    "missing_records",
                    max=t.max_missing_records,
                    source="threshold",
                )
            )
        if t.max_missing_percentage is not None:
            rs.add(
                MetricRule(
                    "max_missing_percentage",
                    "missing_percentage",
                    max=t.max_missing_percentage,
                    source="threshold",
                )
            )
        global_mismatch = (
            t.max_mismatched_records is not None or t.max_mismatch_percentage is not None
        )
        if t.max_mismatched_records is not None:
            rs.add(
                MetricRule(
                    "max_mismatched_records",
                    "mismatched_records",
                    max=t.max_mismatched_records,
                    source="threshold",
                )
            )
        if t.max_mismatch_percentage is not None:
            rs.add(
                MetricRule(
                    "max_mismatch_percentage",
                    "mismatch_percentage",
                    max=t.max_mismatch_percentage,
                    source="threshold",
                )
            )
        rs.add(
            MetricRule(
                "max_duplicate_keys" if t.max_duplicate_keys is not None else "no_duplicate_keys",
                "duplicate_keys",
                max=t.max_duplicate_keys or 0,
                severity="error" if t.max_duplicate_keys is not None else "warning",
                source="threshold" if t.max_duplicate_keys is not None else "default",
            )
        )
        rs.add(
            MetricRule(
                "max_schema_changes" if t.max_schema_changes is not None else "no_schema_changes",
                "schema_changes",
                max=t.max_schema_changes or 0,
                severity="error" if t.max_schema_changes is not None else "warning",
                source="threshold" if t.max_schema_changes is not None else "default",
            )
        )
        ruled = {r.column for r in cfg.rules if r.column}
        for col in compare_columns:
            opts = cfg.column_options(col)
            if opts.critical:
                rs.add(
                    MetricRule(
                        f"critical_{col}", "column_mismatches", max=0, column=col, source="column"
                    )
                )
                continue
            if opts.max_mismatch_percentage is not None:
                rs.add(
                    MetricRule(
                        f"{col}_max_mismatch_percentage",
                        "column_mismatch_percentage",
                        max=opts.max_mismatch_percentage,
                        column=col,
                        source="column",
                    )
                )
            if opts.max_mismatches is not None:
                rs.add(
                    MetricRule(
                        f"{col}_max_mismatches",
                        "column_mismatches",
                        max=opts.max_mismatches,
                        column=col,
                        source="column",
                    )
                )
            has_own = opts.max_mismatch_percentage is not None or opts.max_mismatches is not None
            if not (global_mismatch or has_own or col in ruled):
                rs.add(
                    MetricRule(
                        f"{col}_matches", "column_mismatches", max=0, column=col, source="default"
                    )
                )
        for rule in cfg.rules:
            metric = rule.effective_metric
            maximum = rule.max
            if maximum is None and rule.min is None:
                maximum = 0.0
            rs.add(
                MetricRule(
                    rule.name,
                    metric,
                    max=maximum,
                    min=rule.min,
                    column=rule.column,
                    severity=rule.severity,
                    source="rule",
                    description=rule.description,
                )
            )
        return rs


def overall_status(results: list[RuleResult]) -> Status:
    outcomes = {r.outcome for r in results}
    if Outcome.FAIL in outcomes:
        return Status.FAIL
    if Outcome.WARNING in outcomes:
        return Status.PASS_WITH_WARNINGS
    return Status.PASS
