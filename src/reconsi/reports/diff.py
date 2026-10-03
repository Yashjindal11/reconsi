"""Compare two reconciliation runs (result documents)."""

from __future__ import annotations

from typing import Any

SUMMARY_METRICS = (
    "left_rows",
    "right_rows",
    "matched_records",
    "value_mismatch_records",
    "missing_left",
    "missing_right",
    "ambiguous_records",
    "match_percentage",
    "mismatch_percentage",
)


def diff_documents(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What changed between two runs: status, summary metrics, per-column mismatches, inputs."""
    metrics = []
    for key in SUMMARY_METRICS:
        a, b = before["summary"].get(key), after["summary"].get(key)
        if a is None or b is None:
            continue
        metrics.append({"metric": key, "before": a, "after": b, "change": b - a})
    columns = []
    for col in sorted(set(before["columns"]) | set(after["columns"])):
        a = (before["columns"].get(col) or {}).get("mismatches")
        b = (after["columns"].get(col) or {}).get("mismatches")
        if a != b:
            columns.append({"column": col, "before": a, "after": b})
    inputs = {}
    for side in ("left", "right"):
        da = (before["metadata"].get(f"{side}_fingerprint") or {}).get("digest")
        db = (after["metadata"].get(f"{side}_fingerprint") or {}).get("digest")
        inputs[side] = {"before": da, "after": db, "changed": da != db}
    before_titles = {f["title"] for f in before["findings"]}
    after_titles = {f["title"] for f in after["findings"]}
    return {
        "before": {
            "name": before["name"],
            "run_id": before["metadata"].get("run_id"),
            "status": before["status"],
        },
        "after": {
            "name": after["name"],
            "run_id": after["metadata"].get("run_id"),
            "status": after["status"],
        },
        "status_changed": before["status"] != after["status"],
        "metrics": metrics,
        "columns": columns,
        "inputs": inputs,
        "configuration_changed": before["metadata"].get("config_hash")
        != after["metadata"].get("config_hash"),
        "new_findings": sorted(after_titles - before_titles),
        "resolved_findings": sorted(before_titles - after_titles),
    }


def render_diff(diff: dict[str, Any]) -> str:
    lines = [
        f"Status: {diff['before']['status']} -> {diff['after']['status']}",
        f"Inputs changed: left={diff['inputs']['left']['changed']}, "
        f"right={diff['inputs']['right']['changed']}; configuration changed: "
        f"{diff['configuration_changed']}",
        "",
        f"{'metric':<26}{'before':>16}{'after':>16}{'change':>16}",
    ]
    for m in diff["metrics"]:
        lines.append(
            f"{m['metric']:<26}{_n(m['before']):>16}{_n(m['after']):>16}{_n(m['change'], sign=True):>16}"
        )
    if diff["columns"]:
        lines += ["", "Column mismatches changed:"]
        lines += [f"  {c['column']}: {c['before']} -> {c['after']}" for c in diff["columns"]]
    if diff["new_findings"]:
        lines += ["", "New findings:"] + [f"  + {t}" for t in diff["new_findings"]]
    if diff["resolved_findings"]:
        lines += ["", "Resolved findings:"] + [f"  - {t}" for t in diff["resolved_findings"]]
    return "\n".join(lines)


def _n(v: float, sign: bool = False) -> str:
    if isinstance(v, int) or float(v).is_integer():
        return f"{int(v):+,}" if sign else f"{int(v):,}"
    return f"{v:+.3f}" if sign else f"{v:.3f}"
