"""Plain-text terminal rendering for the CLI."""

from __future__ import annotations

from typing import Any

import pandas as pd

STATUS_WORD = {"PASS": "PASS", "PASS_WITH_WARNINGS": "PASS WITH WARNINGS", "FAIL": "FAIL"}
EVIDENCE_SHORT = {
    "observed": "observed",
    "statistically_supported": "statistical",
    "likely_explanation": "likely",
    "user_configured_rule": "rule",
}


def _pct(x: float) -> str:
    return f"{x:.2f}%"


def summary_text(doc: dict[str, Any], *, max_findings: int = 10) -> str:
    s = doc["summary"]
    lines = [
        f"ReconSI  {doc['name']}",
        f"Status   {STATUS_WORD.get(doc['status'], doc['status'])}",
        "",
        f"  left rows            {s['left_rows']:>12,}",
        f"  right rows           {s['right_rows']:>12,}",
        f"  matched              {s['matched_records']:>12,}  ({_pct(s['match_percentage'])})",
        f"  value mismatches     {s['value_mismatch_records']:>12,}  ({_pct(s['mismatch_percentage'])} of compared)",
        f"  missing from right   {s['missing_right']:>12,}",
        f"  missing from left    {s['missing_left']:>12,}",
        f"  duplicate keys       {s['duplicate_keys_left']:>6,} left / {s['duplicate_keys_right']:,} right",
    ]
    if s["ambiguous_records"]:
        lines.append(f"  ambiguous (set aside){s['ambiguous_records']:>12,}")
    mismatched = [c for c in doc["columns"].values() if c["mismatches"]]
    if mismatched:
        lines += ["", "Columns with mismatches:"]
        for c in sorted(mismatched, key=lambda c: -c["mismatches"])[:10]:
            lines.append(
                f"  {c['column']:<24}{c['mismatches']:>10,}  {c['mismatch_percentage']:.2f}%  {c['classification']}"
            )
    findings = [f for f in doc["findings"] if f["category"] != "rules"]
    if findings:
        lines += ["", "Findings:"]
        for f in findings[:max_findings]:
            lines.append(
                f"  [{f['severity']}/{EVIDENCE_SHORT.get(f['evidence'], f['evidence'])}] {f['title']}"
            )
        if len(findings) > max_findings:
            lines.append(f"  ... {len(findings) - max_findings} more in the report")
    return "\n".join(lines)


def frame_text(frame: pd.DataFrame, max_rows: int = 50) -> str:
    if frame.empty:
        return "(none)"
    with pd.option_context("display.max_columns", 30, "display.width", 160):
        return str(frame.head(max_rows).to_string(index=False))
