"""Turn analysis output into ranked, evidence-labelled findings and recommendations.

Every finding carries an :class:`~reconsi.core.types.Evidence` label:

* ``observed`` - a direct count or measurement;
* ``statistically_supported`` - passed a stated statistical test;
* ``likely_explanation`` - a heuristic diagnosis that fits the evidence but is not proven;
* ``user_configured_rule`` - the outcome of a rule or threshold the user configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from reconsi.core.serialization import to_jsonable
from reconsi.core.types import Evidence, Severity

if TYPE_CHECKING:
    from reconsi.core.result import ReconciliationResult

SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}


@dataclass(frozen=True)
class Finding:
    id: str
    category: str
    severity: Severity
    evidence: Evidence
    title: str
    detail: str = ""
    recommendation: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "severity": self.severity.value,
            "evidence": self.evidence.value,
            "title": self.title,
            "detail": self.detail,
            "recommendation": self.recommendation,
            "data": to_jsonable(self.data),
        }


def _pct(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}%"


def _n(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.4g}"


class _Builder:
    def __init__(self) -> None:
        self.items: list[Finding] = []
        self._counts: dict[str, int] = {}

    def add(
        self,
        category: str,
        severity: Severity,
        evidence: Evidence,
        title: str,
        detail: str = "",
        recommendation: str | None = None,
        **data: Any,
    ) -> None:
        n = self._counts.get(category, 0) + 1
        self._counts[category] = n
        self.items.append(
            Finding(
                f"{category}-{n}", category, severity, evidence, title, detail, recommendation, data
            )
        )


def generate_findings(result: ReconciliationResult) -> list[Finding]:
    f = _Builder()
    _rules(f, result)
    _records(f, result)
    _keys(f, result)
    _grain(f, result)
    _columns(f, result)
    _statistics(f, result)
    _schema(f, result)
    _notes(f, result)
    return sorted(f.items, key=lambda x: SEVERITY_ORDER[x.severity])


def recommendations(findings: list[Finding]) -> list[str]:
    seen: list[str] = []
    for finding in findings:
        if finding.recommendation and finding.recommendation not in seen:
            seen.append(finding.recommendation)
    return seen


def _rules(f: _Builder, r: ReconciliationResult) -> None:
    for rule in r.rule_results:
        if rule.outcome.value == "fail":
            f.add(
                "rules",
                Severity.CRITICAL,
                Evidence.RULE,
                f"Rule failed: {rule.name}",
                rule.message,
                source=rule.source,
            )
        elif rule.outcome.value == "warning":
            f.add(
                "rules",
                Severity.WARNING,
                Evidence.RULE,
                f"Rule warning: {rule.name}",
                rule.message,
                source=rule.source,
            )


def _records(f: _Builder, r: ReconciliationResult) -> None:
    s = r.summary
    total = s["total_records"] or 1
    for key, side, other in (("missing_right", "left", "right"), ("missing_left", "right", "left")):
        n = s[key]
        if n:
            f.add(
                "records",
                Severity.WARNING,
                Evidence.OBSERVED,
                f"{_n(n)} records in the {side} dataset are missing from the {other} dataset",
                f"{_pct(100 * n / total)} of all {_n(s['total_records'])} records.",
                "Check extraction filters, load windows and key formatting for the missing records "
                "(see unmatched population and key diagnosis).",
                count=n,
            )
    if s["value_mismatch_records"]:
        f.add(
            "records",
            Severity.WARNING,
            Evidence.OBSERVED,
            f"{_n(s['value_mismatch_records'])} matched records have differing values",
            f"{_pct(s['mismatch_percentage'])} of {_n(s['compared_records'])} records present on both sides.",
            count=s["value_mismatch_records"],
        )


def _keys(f: _Builder, r: ReconciliationResult) -> None:
    ka = r.keys
    keys = " + ".join(ka.keys)
    for side in (ka.left, ka.right):
        if side.duplicate_keys:
            f.add(
                "keys",
                Severity.WARNING,
                Evidence.OBSERVED,
                f"{keys} is not unique in the {side.side} dataset",
                f"{_n(side.rows)} rows, {_n(side.unique_keys)} unique keys; {_n(side.duplicate_keys)} keys are "
                f"duplicated (max {side.max_multiplicity} rows per key, mean {side.mean_records_per_key:.2f}).",
                "Confirm the grain of each dataset; choose a duplicate_strategy (aggregate, first, "
                "last, multiset) or reconcile at a coarser grain with left_group_by/right_group_by.",
                side=side.side,
            )
        if side.null_keys:
            f.add(
                "keys",
                Severity.WARNING,
                Evidence.OBSERVED,
                f"{_n(side.null_keys)} rows in the {side.side} dataset have a null key",
                "Rows with null keys can never be matched and are reported as missing.",
                "Investigate why key values are null at the source.",
            )
        for col, issues in side.format_issues.items():
            parts = []
            if issues.blank:
                parts.append(f"{_n(issues.blank)} blank")
            if issues.whitespace:
                parts.append(f"{_n(issues.whitespace)} with leading/trailing whitespace")
            if issues.case_variants:
                parts.append(f"{_n(issues.case_variants)} that differ only by case")
            if issues.malformed:
                parts.append(
                    f"{_n(issues.malformed)} not matching the dominant pattern {issues.dominant_pattern!r}"
                )
            if parts:
                f.add(
                    "keys",
                    Severity.WARNING,
                    Evidence.OBSERVED,
                    f"Key column {col} has formatting issues in the {side.side} dataset",
                    "Values: " + ", ".join(parts) + ".",
                    examples=issues.malformed_examples,
                )
    if ka.relationship == "many-to-many":
        f.add(
            "keys",
            Severity.CRITICAL,
            Evidence.OBSERVED,
            "Many-to-many reconciliation risk",
            f"Mean records per key: left {ka.left.mean_records_per_key:.2f}, right "
            f"{ka.right.mean_records_per_key:.2f}. A naive join on {keys} would produce "
            f"{_n(ka.naive_join_rows)} rows for {_n(ka.common_keys)} common keys "
            f"({_n(ka.join_inflation)} extra), inflating any totals computed from it.",
            "Do not sum values over a join on these keys; aggregate each side to the key first.",
        )
    elif ka.join_inflation:
        f.add(
            "keys",
            Severity.WARNING,
            Evidence.OBSERVED,
            f"A naive join on {keys} would duplicate rows ({ka.relationship})",
            f"{_n(ka.naive_join_rows)} joined rows for {_n(ka.common_keys)} common keys.",
        )
    for mismatch in ka.dtype_mismatches:
        f.add(
            "keys",
            Severity.WARNING,
            Evidence.OBSERVED,
            f"Key column {mismatch['column']} has different types ({mismatch['left']} vs {mismatch['right']})",
            "Keys were compared as canonical text.",
            "Align key types at the source to avoid silent formatting differences.",
        )
    for diag in ka.normalization_diagnosis[:2]:
        f.add(
            "keys",
            Severity.WARNING,
            Evidence.LIKELY,
            f"{_n(diag['would_match'])} unmatched keys would match after {diag['normalization']}",
            f"{_pct(100 * diag['share_of_left_only'])} of keys found only on the left have a "
            f"counterpart on the right once '{diag['normalization']}' is applied to both sides. "
            f"Examples: {', '.join(diag['examples'][:3])}.",
            f"If these are the same entities, set key_normalize: [{diag['normalization']}] "
            "(or fix the formatting upstream).",
        )


def _grain(f: _Builder, r: ReconciliationResult) -> None:
    grain = r.analyses.get("grain")
    if grain and grain.get("relationship") in ("left_finer", "right_finer", "different"):
        f.add(
            "grain",
            Severity.INFO,
            Evidence.LIKELY,
            "The datasets appear to be at different grains",
            f"Left appears to be at {grain['left']['description']}; right appears to be at "
            f"{grain['right']['description']} (an inference from observed uniqueness).",
        )
    diag = r.analyses.get("aggregation_diagnosis")
    if diag:
        if diag["explained_by_grain"]:
            f.add(
                "grain",
                Severity.WARNING,
                Evidence.LIKELY,
                "Differences are explained by grain: totals agree after aggregation",
                diag["conclusion"],
                f"Reconcile at the coarser grain: left_group_by={diag['keys']} with aggregations.",
            )
        else:
            f.add(
                "grain",
                Severity.INFO,
                Evidence.OBSERVED,
                "Aggregating per key does not remove the differences",
                diag["conclusion"],
            )


def _columns(f: _Builder, r: ReconciliationResult) -> None:
    for col, st in r.columns.items():
        d = st.to_dict()
        if st.datatype_mismatch:
            f.add(
                "values",
                Severity.WARNING,
                Evidence.OBSERVED,
                f"Column {col} has different types ({st.left_dtype} vs {st.right_dtype})",
                f"Compared as {st.kind}.",
                f"Set an explicit type for {col} (columns.{col}.type) or align types upstream.",
            )
        if st.mismatches:
            lo, hi = d["mismatch_percentage_ci95"]
            detail = (
                f"{_n(st.mismatches)} of {_n(st.compared)} compared values differ "
                f"({_pct(d['mismatch_percentage'])}; 95% CI {_pct(lo)}-{_pct(hi)}). "
                f"Types: {', '.join(f'{k}={v}' for k, v in st.mismatch_types.items())}."
            )
            if st.totals:
                detail += f" Total difference {_n(st.totals['difference'] or 0)}."
            f.add(
                "values",
                Severity.WARNING,
                Evidence.OBSERVED,
                f"{col}: {st.classification.replace('_', ' ')}",
                detail,
                column=col,
            )
        elif st.within_tolerance:
            f.add(
                "values",
                Severity.INFO,
                Evidence.OBSERVED,
                f"{col}: {_n(st.within_tolerance)} values match only within tolerance",
                f"Comparison settings: {st.effective}.",
            )
        for hint in st.hints:
            _hint(f, col, hint)


def _hint(f: _Builder, col: str, hint: dict[str, Any]) -> None:
    kind = hint["kind"]
    if kind == "string_normalization":
        f.add(
            "values",
            Severity.WARNING,
            Evidence.LIKELY,
            f"{col}: {_n(hint['would_resolve'])} of {_n(hint['of_mismatches'])} string mismatches are formatting only",
            f"They disappear with '{hint['normalization']}' normalisation (not applied).",
            f"If formatting differences are acceptable, set columns.{col}.normalize.",
        )
    elif kind == "constant_offset":
        f.add(
            "values",
            Severity.WARNING,
            Evidence.LIKELY,
            f"{col}: timestamps differ by a constant {hint['offset']}",
            f"{_pct(100 * hint['share'])} of datetime mismatches share this offset. {hint['message']}",
            f"Check the timezone of each source; set columns.{col}.timezone for naive timestamps.",
        )
    elif kind == "precision":
        f.add(
            "values",
            Severity.INFO,
            Evidence.LIKELY,
            f"{col}: {_n(hint['would_resolve'])} of {_n(hint['of_mismatches'])} timestamp mismatches vanish at {hint['precision']} precision",
            "The sources may store timestamps at different precision.",
            f"Consider columns.{col}.tolerance_seconds.",
        )
    elif kind == "timezone_assumption":
        f.add(
            "values",
            Severity.WARNING,
            Evidence.OBSERVED,
            f"{col}: timezone-aware vs naive timestamps",
            hint["message"],
        )


def _statistics(f: _Builder, r: ReconciliationResult) -> None:
    a = r.analyses
    for col, bias in (a.get("bias") or {}).items():
        if bias.get("systematic"):
            f.add(
                "bias",
                Severity.WARNING,
                Evidence.STATISTICAL,
                f"{col}: systematic difference detected",
                bias["message"],
                "Look for a shared cause such as a fee, tax, FX rate, rounding rule or a changed "
                "formula; a systematic difference is not necessarily an error.",
            )
    for col, dist in ((a.get("distributions") or {}).get("columns") or {}).items():
        if dist.get("shift"):
            if dist["type"] == "numeric":
                detail = (
                    f"KS={dist['ks_statistic']:.3f} (p={dist['ks_p_value']:.2g}), standardised mean "
                    f"difference {dist['standardized_mean_difference']:.2f}."
                )
            else:
                detail = (
                    f"Chi-square p={dist['chi_square_p_value']:.2g}, Jensen-Shannon divergence "
                    f"{dist['jensen_shannon_divergence']:.3f}."
                )
            f.add(
                "distribution",
                Severity.INFO,
                Evidence.STATISTICAL,
                f"{col}: the distribution differs between datasets",
                detail,
            )
    for conc in a.get("concentration") or []:
        if conc.get("concentrated"):
            f.add(
                "concentration",
                Severity.WARNING,
                Evidence.STATISTICAL,
                f"Problems concentrate in {conc['dimension']} = {conc['top_level']['level']}",
                conc["message"] + f" (chi-square, Bonferroni p={conc['p_value_bonferroni']:.2g}).",
                f"Drill down: result.drill_down({conc['dimension']!r}).",
            )
    for label, pop in (a.get("unmatched_population") or {}).items():
        side = "right" if label == "missing_from_right" else "left"
        for dim in pop["dimensions"]:
            if dim["significant"] and dim["over_represented"]:
                top = dim["over_represented"][0]
                f.add(
                    "unmatched",
                    Severity.WARNING,
                    Evidence.STATISTICAL,
                    f"Records missing from the {side} are disproportionately {dim['dimension']} = {top['level']}",
                    f"{_pct(100 * top['share_of_missing'], 1)} of missing records vs "
                    f"{_pct(100 * top['share_of_present'], 1)} of matched records "
                    f"(Bonferroni p={dim['p_value_bonferroni']:.2g}).",
                    "Check filters or partitions for this segment in the extract that is missing it.",
                )
    temporal = a.get("temporal") or {}
    for anomaly in temporal.get("anomalous_periods", []):
        f.add(
            "temporal",
            Severity.WARNING,
            Evidence.STATISTICAL,
            f"Reconciliation degraded on {str(anomaly['period'])[:10]}",
            f"Problem rate {_pct(100 * anomaly['problem_rate'])} vs {_pct(100 * anomaly['baseline_rate'])} "
            f"in other periods (binomial test, Bonferroni p={anomaly['p_value_bonferroni']:.2g}).",
        )
    for cp in temporal.get("change_points", []):
        f.add(
            "temporal",
            Severity.WARNING,
            Evidence.STATISTICAL,
            "Change point in the mismatch rate",
            cp["message"],
        )
    for col, tot in ((a.get("control_totals") or {}).get("columns") or {}).items():
        if tot["difference"]:
            rel = tot.get("relative_difference")
            f.add(
                "totals",
                Severity.INFO,
                Evidence.OBSERVED,
                f"Control total for {col} differs by {_n(tot['difference'])}",
                f"Left {_n(tot['left_sum'])}, right {_n(tot['right_sum'])}"
                + (f" ({_pct(100 * rel, 3)})." if rel is not None else "."),
            )


def _schema(f: _Builder, r: ReconciliationResult) -> None:
    sd = r.schema
    if sd.added:
        f.add(
            "schema",
            Severity.INFO,
            Evidence.OBSERVED,
            f"{len(sd.added)} columns only in the right dataset",
            ", ".join(sd.added),
        )
    if sd.removed:
        f.add(
            "schema",
            Severity.INFO,
            Evidence.OBSERVED,
            f"{len(sd.removed)} columns only in the left dataset",
            ", ".join(sd.removed),
        )
    for s in sd.suggestions:
        f.add(
            "schema",
            Severity.INFO,
            Evidence.LIKELY,
            f"Suggested column match: {s.left} <-> {s.right}",
            f"Score {s.score:.2f} from name, type, uniqueness and value overlap. Not applied.",
            f"If correct, add column_mapping: {{{s.left}: {s.right}}}.",
        )


def _notes(f: _Builder, r: ReconciliationResult) -> None:
    for note in r.notes:
        if note["kind"] == "ambiguous":
            f.add(
                "duplicates",
                Severity.WARNING,
                Evidence.OBSERVED,
                "Duplicate keys were set aside",
                note["message"],
            )
