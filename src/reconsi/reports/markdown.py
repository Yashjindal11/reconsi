"""Markdown report for GitHub, pull requests and analyst review. Renders a result *document*."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

STATUS_TEXT = {
    "PASS": "PASS",
    "PASS_WITH_WARNINGS": "PASS WITH WARNINGS",
    "FAIL": "FAIL",
}
EVIDENCE_TEXT = {
    "observed": "Observed",
    "statistically_supported": "Statistically supported",
    "likely_explanation": "Likely explanation",
    "user_configured_rule": "User-configured rule",
}


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        text = f"{value:,.6g}"
    elif isinstance(value, int) and not isinstance(value, bool):
        text = f"{value:,}"
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    if not rows:
        return "_None._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def _pct(x: float | None) -> str:
    return "" if x is None else f"{x:.2f}%"


def render_markdown(doc: dict[str, Any], *, max_rows: int = 20) -> str:
    s = doc["summary"]
    meta = doc["metadata"]
    lines: list[str] = [
        f"# Reconciliation report: {doc['name']}",
        "",
        f"**Status: {STATUS_TEXT.get(doc['status'], doc['status'])}**",
        "",
        f"Left: `{meta['left'].get('path') or meta['left']['name']}` ({s['left_rows']:,} rows) | "
        f"Right: `{meta['right'].get('path') or meta['right']['name']}` ({s['right_rows']:,} rows) | "
        f"Keys: `{', '.join(s['keys'])}`",
        "",
        "## Executive summary",
        "",
        table(
            ["Measure", "Value"],
            [
                ["Records (union of keys)", s["total_records"]],
                ["Matched", f"{s['matched_records']:,} ({_pct(s['match_percentage'])})"],
                [
                    "Value mismatches",
                    f"{s['value_mismatch_records']:,} ({_pct(s['mismatch_percentage'])} of compared)",
                ],
                ["Missing from right (left only)", s["missing_right"]],
                ["Missing from left (right only)", s["missing_left"]],
                ["Ambiguous (duplicate keys set aside)", s["ambiguous_records"]],
                [
                    "Duplicate keys (left / right)",
                    f"{s['duplicate_keys_left']:,} / {s['duplicate_keys_right']:,}",
                ],
                [
                    "Columns compared / with mismatches",
                    f"{s['columns_compared']} / {s['columns_with_mismatches']}",
                ],
            ],
        ),
    ]
    findings = doc["findings"]
    lines += ["## Findings", ""]
    if findings:
        lines.append(
            table(
                ["Severity", "Evidence", "Finding", "Detail"],
                [
                    [
                        f["severity"],
                        EVIDENCE_TEXT.get(f["evidence"], f["evidence"]),
                        f["title"],
                        f["detail"],
                    ]
                    for f in findings[: max_rows * 2]
                ],
            )
        )
    else:
        lines.append("_No findings._\n")
    if doc.get("recommendations"):
        lines += ["## Recommendations", ""]
        lines += [f"{i}. {r}" for i, r in enumerate(doc["recommendations"], 1)]
        lines.append("")
    lines += _rules(doc)
    lines += _schema(doc)
    lines += _keys(doc)
    lines += _columns(doc)
    lines += _analyses(doc, max_rows)
    lines += _samples(doc, max_rows)
    lines += [
        "## Reproducibility",
        "",
        table(
            ["Item", "Value"],
            [
                ["ReconSI version", meta.get("reconsi_version")],
                ["Python", meta.get("python_version")],
                ["Started (UTC)", meta.get("started_at")],
                ["Duration (s)", meta.get("duration_seconds")],
                ["Backend", meta.get("backend")],
                ["Seed", meta.get("seed")],
                ["Git commit", meta.get("git_commit")],
                ["Left fingerprint", (meta.get("left_fingerprint") or {}).get("digest")],
                ["Right fingerprint", (meta.get("right_fingerprint") or {}).get("digest")],
            ],
        ),
        "_Evidence labels: Observed = direct measurement; Statistically supported = passed a "
        "stated test; Likely explanation = heuristic diagnosis, not proof; User-configured rule = "
        "outcome of a configured threshold._",
        "",
    ]
    return "\n".join(lines)


def _rules(doc: dict[str, Any]) -> list[str]:
    rows = [
        [r["name"], r["outcome"], r["severity"], r["source"], r["message"]] for r in doc["rules"]
    ]
    return ["## Rules", "", table(["Rule", "Outcome", "Severity", "Source", "Detail"], rows)]


def _schema(doc: dict[str, Any]) -> list[str]:
    sd = doc["schema"]
    out = [
        "## Schema differences",
        "",
        f"Left: {sd['left']['column_count']} columns. Right: {sd['right']['column_count']} columns. "
        f"Column order changed: {'yes' if sd['order_changed'] else 'no'}.",
        "",
    ]
    if sd["added_columns"]:
        out.append(f"- Only in right: {', '.join(f'`{c}`' for c in sd['added_columns'])}")
    if sd["removed_columns"]:
        out.append(f"- Only in left: {', '.join(f'`{c}`' for c in sd['removed_columns'])}")
    for c in sd["dtype_changes"]:
        out.append(
            f"- `{c['column']}`: {c['left_dtype']} -> {c['right_dtype']}"
            + ("" if c["compatible"] else " (incompatible)")
        )
    for s in sd["suggested_column_matches"]:
        out.append(
            f"- Suggestion (not applied): `{s['left']}` <-> `{s['right']}` (score {s['score']})"
        )
    if sd["identical"]:
        out.append("- Schemas are identical.")
    out.append("")
    return out


def _keys(doc: dict[str, Any]) -> list[str]:
    k = doc["keys"]
    rows = []
    for side in ("left", "right"):
        p = k[side]
        rows.append(
            [
                side,
                p["rows"],
                p["unique_keys"],
                p["duplicate_keys"],
                p["max_multiplicity"],
                f"{p['mean_records_per_key']:.3f}",
                p["null_keys"],
            ]
        )
    out = [
        "## Key analysis",
        "",
        f"Relationship: **{k['relationship']}**. Common keys: {k['common_keys']:,}; left only: "
        f"{k['left_only_keys']:,}; right only: {k['right_only_keys']:,}. A naive join would "
        f"produce {k['naive_join_rows']:,} rows.",
        "",
        table(
            [
                "Side",
                "Rows",
                "Unique keys",
                "Duplicated keys",
                "Max rows/key",
                "Mean rows/key",
                "Null keys",
            ],
            rows,
        ),
    ]
    if k["normalization_diagnosis"]:
        out.append(
            table(
                ["Normalisation (diagnostic only)", "Unmatched keys that would match"],
                [[d["normalization"], d["would_match"]] for d in k["normalization_diagnosis"]],
            )
        )
    return out


def _columns(doc: dict[str, Any]) -> list[str]:
    rows = []
    for c in doc["columns"].values():
        d = c.get("differences") or {}
        rows.append(
            [
                c["column"],
                c["kind"],
                c["classification"],
                c["compared"],
                c["mismatches"],
                _pct(c["match_percentage"]),
                c["within_tolerance"],
                c["null_mismatches"],
                d.get("mean"),
                d.get("median"),
            ]
        )
    return [
        "## Column reconciliation",
        "",
        table(
            [
                "Column",
                "Kind",
                "Classification",
                "Compared",
                "Mismatches",
                "Match %",
                "Within tolerance",
                "Null mismatches",
                "Mean diff",
                "Median diff",
            ],
            rows,
        ),
    ]


def _analyses(doc: dict[str, Any], max_rows: int) -> list[str]:
    a = doc["analyses"]
    out: list[str] = []
    bias = [(c, b) for c, b in (a.get("bias") or {}).items() if b.get("tested")]
    if bias:
        out += [
            "## Numeric differences and systematic bias",
            "",
            table(
                [
                    "Column",
                    "Differing pairs",
                    "Right higher",
                    "Right lower",
                    "Median diff",
                    "Sign test p",
                    "Systematic",
                ],
                [
                    [
                        c,
                        b["differing_pairs"],
                        b["positive"],
                        b["negative"],
                        b["median_signed_difference"],
                        b["sign_test_p_value"],
                        "yes" if b["systematic"] else "no",
                    ]
                    for c, b in bias
                ],
            ),
        ]
    totals = (a.get("control_totals") or {}).get("columns") or {}
    if totals:
        out += [
            "## Control totals",
            "",
            table(
                ["Column", "Left sum", "Right sum", "Difference", "Relative"],
                [
                    [c, t["left_sum"], t["right_sum"], t["difference"], t["relative_difference"]]
                    for c, t in totals.items()
                ],
            ),
        ]
    dists = (a.get("distributions") or {}).get("columns") or {}
    if dists:
        rows = []
        for col, d in dists.items():
            if not d.get("tested"):
                continue
            if d["type"] == "numeric":
                rows.append(
                    [
                        col,
                        "numeric",
                        f"KS={d['ks_statistic']:.3f}",
                        d["ks_p_value"],
                        f"W={d['wasserstein_distance']:.4g}",
                        "yes" if d["shift"] else "no",
                    ]
                )
            else:
                rows.append(
                    [
                        col,
                        "categorical",
                        f"chi2={d['chi_square']:.4g}",
                        d["chi_square_p_value"],
                        f"JSD={d['jensen_shannon_divergence']:.4f}",
                        "yes" if d["shift"] else "no",
                    ]
                )
        out += [
            "## Distribution differences",
            "",
            table(["Column", "Type", "Statistic", "p-value", "Effect size", "Shift"], rows),
        ]
    conc = a.get("concentration") or []
    if conc:
        out += ["## Mismatch concentration", ""]
        for entry in conc[:5]:
            out.append(
                f"### {entry['dimension']}" + (" (concentrated)" if entry["concentrated"] else "")
            )
            out.append("")
            out.append(
                table(
                    [
                        entry["dimension"],
                        "Records",
                        "Problems",
                        "Problem rate",
                        "Share of problems",
                        "Lift",
                    ],
                    [
                        [
                            lv[entry["dimension"]],
                            lv["records"],
                            lv["problems"],
                            f"{100 * lv['problem_rate']:.2f}%",
                            f"{100 * lv['share_of_problems']:.1f}%",
                            f"{lv['lift']:.2f}",
                        ]
                        for lv in entry["levels"][:max_rows]
                    ],
                )
            )
    temporal = a.get("temporal")
    if temporal:
        out += [
            "## Temporal analysis",
            "",
            table(
                [
                    "Period",
                    "Records",
                    "Match %",
                    "Value mismatches",
                    "Missing left",
                    "Missing right",
                ],
                [
                    [
                        str(p["period"])[:10],
                        p["records"],
                        f"{100 * p['match_rate']:.2f}%",
                        p["value_mismatch"],
                        p["missing_left"],
                        p["missing_right"],
                    ]
                    for p in temporal["periods"][-max_rows * 2 :]
                ],
            ),
        ]
        for cp in temporal["change_points"]:
            out.append(f"- {cp['message']}")
        out.append("")
    return out


def _samples(doc: dict[str, Any], max_rows: int) -> list[str]:
    out: list[str] = []
    rec = doc["records"]
    for title, key in (
        ("Value mismatches (sample)", "value_mismatch_sample"),
        ("Missing from right (sample)", "missing_right_sample"),
        ("Missing from left (sample)", "missing_left_sample"),
        ("Duplicate keys (sample)", "duplicate_keys_sample"),
    ):
        rows = rec.get(key) or []
        if not rows:
            continue
        headers = list(rows[0].keys())
        out += [
            f"## {title}",
            "",
            table(headers, [[r.get(h) for h in headers] for r in rows[:max_rows]]),
        ]
    return out
