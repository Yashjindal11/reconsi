"""Standalone, offline HTML report. Renders a result *document* (``result.to_dict()``)."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from typing import Any

from reconsi.visualization import svg

STATUS_CLASS = {"PASS": "ok", "PASS_WITH_WARNINGS": "warn", "FAIL": "bad"}
STATUS_LABEL = {"PASS": "Pass", "PASS_WITH_WARNINGS": "Pass with warnings", "FAIL": "Fail"}
EVIDENCE_LABEL = {
    "observed": "Observed",
    "statistically_supported": "Statistically supported",
    "likely_explanation": "Likely explanation",
    "user_configured_rule": "User-configured rule",
}

CSS = """
:root{--bg:#fbfaf7;--ink:#1d1d1b;--muted:#6b6b66;--rule:#e4e1d8;--ok:#2f6b3a;--warn:#a86b00;
--bad:#a12a2a;--panel:#ffffff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,
"Segoe UI",Helvetica,Arial,sans-serif}
h1,h2,h3{font-family:Georgia,"Times New Roman",serif;font-weight:normal;letter-spacing:-.01em}
h1{font-size:2.1rem;margin:.2rem 0 .4rem}h2{font-size:1.45rem;margin:2.6rem 0 .8rem;
padding-top:1rem;border-top:1px solid var(--rule)}h3{font-size:1.1rem;margin:1.6rem 0 .5rem}
.layout{display:grid;grid-template-columns:230px 1fr;max-width:1320px;margin:0 auto}
nav{position:sticky;top:0;align-self:start;height:100vh;overflow:auto;padding:2rem 1rem 2rem 1.5rem;
border-right:1px solid var(--rule);font-size:.86rem}
nav a{display:block;color:var(--muted);text-decoration:none;padding:.18rem 0}
nav a:hover{color:var(--ink)}nav .brand{font-family:Georgia,serif;color:var(--ink);font-size:1.05rem;
margin-bottom:1rem}
main{padding:2rem 2.6rem 5rem;min-width:0}
.eyebrow{color:var(--muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.08em}
.status{display:inline-block;padding:.2rem .7rem;border:1px solid currentColor;font-weight:600;
font-size:.9rem;letter-spacing:.04em;text-transform:uppercase}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:0;margin:1.4rem 0;
border-top:1px solid var(--ink);border-bottom:1px solid var(--rule)}
.kpi{padding:.8rem .9rem .9rem 0}.kpi .v{font-family:Georgia,serif;font-size:1.65rem}
.kpi .l{color:var(--muted);font-size:.8rem}
table{border-collapse:collapse;width:100%;margin:.6rem 0 1rem;font-size:.86rem;background:var(--panel)}
th,td{text-align:left;padding:.38rem .55rem;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-weight:600;color:var(--muted);border-bottom:1px solid var(--ink);cursor:pointer;
white-space:nowrap;user-select:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
.filter{margin:.3rem 0;padding:.35rem .5rem;border:1px solid var(--rule);background:var(--panel);
font:inherit;font-size:.85rem;width:280px}
.tag{display:inline-block;font-size:.72rem;padding:0 .35rem;border:1px solid var(--rule);
color:var(--muted);white-space:nowrap}
.sev-critical{color:var(--bad)}.sev-warning{color:var(--warn)}.sev-info{color:var(--muted)}
.note{color:var(--muted);font-size:.85rem}
.finding{padding:.65rem 0;border-bottom:1px solid var(--rule)}
.finding .t{font-weight:600}.finding .d{color:#3b3b38;font-size:.9rem}
.chart{display:block;margin:.4rem 0 1rem}
.legend{display:flex;flex-wrap:wrap;gap:.3rem 1.2rem;font-size:.82rem;margin-bottom:1rem}
.legend i{display:inline-block;width:10px;height:10px;margin-right:.4rem}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.85em}
@media (max-width:900px){.layout{grid-template-columns:1fr}nav{display:none}main{padding:1.2rem}}
@media print{nav{display:none}.layout{display:block}}
"""

JS = """
document.querySelectorAll('table.data').forEach(function(t){
  t.querySelectorAll('th').forEach(function(th,i){
    th.addEventListener('click',function(){
      var body=t.tBodies[0];var rows=Array.prototype.slice.call(body.rows);
      var asc=th.getAttribute('data-dir')!=='asc';th.setAttribute('data-dir',asc?'asc':'desc');
      rows.sort(function(a,b){
        var x=a.cells[i].getAttribute('data-v')||a.cells[i].textContent;
        var y=b.cells[i].getAttribute('data-v')||b.cells[i].textContent;
        var nx=parseFloat(x),ny=parseFloat(y);
        var c=(!isNaN(nx)&&!isNaN(ny))?nx-ny:x.localeCompare(y);
        return asc?c:-c;});
      rows.forEach(function(r){body.appendChild(r);});
    });
  });
});
document.querySelectorAll('input.filter').forEach(function(inp){
  inp.addEventListener('input',function(){
    var t=document.getElementById(inp.getAttribute('data-target'));var q=inp.value.toLowerCase();
    Array.prototype.forEach.call(t.tBodies[0].rows,function(r){
      r.style.display=r.textContent.toLowerCase().indexOf(q)>=0?'':'none';});
  });
});
"""

SECTIONS = [
    ("summary", "Executive summary"),
    ("status", "Overall status"),
    ("datasets", "Dataset overview"),
    ("schema", "Schema differences"),
    ("keys", "Key analysis"),
    ("records", "Record reconciliation"),
    ("columns", "Column reconciliation"),
    ("numeric", "Numeric differences"),
    ("distributions", "Distribution differences"),
    ("missing", "Missing records"),
    ("duplicates", "Duplicate keys"),
    ("concentration", "Mismatch concentration"),
    ("temporal", "Temporal analysis"),
    ("findings", "Findings"),
    ("recommendations", "Recommendations"),
    ("reproducibility", "Reproducibility"),
]


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value != 0 and (abs(value) < 1e-3 or abs(value) >= 1e9):
            return f"{value:.3g}"
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)


def _pct(value: float | None, digits: int = 2) -> str:
    return "" if value is None else f"{value:.{digits}f}%"


class _Tables:
    def __init__(self) -> None:
        self.n = 0

    def __call__(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
        *,
        filterable: bool = False,
        empty: str = "None.",
    ) -> str:
        if not rows:
            return f'<p class="note">{escape(empty)}</p>'
        self.n += 1
        tid = f"t{self.n}"
        numeric = [
            all(
                (isinstance(r[i], int | float) and not isinstance(r[i], bool)) or r[i] is None
                for r in rows
            )
            for i in range(len(headers))
        ]
        head = "".join(
            f'<th class="{"num" if numeric[i] else ""}">{escape(h)}</th>'
            for i, h in enumerate(headers)
        )
        body = []
        for r in rows:
            cells = []
            for i, v in enumerate(r):
                if isinstance(v, _Raw):
                    cells.append(f"<td>{v.html}</td>")
                elif numeric[i]:
                    sort = "" if v is None else f' data-v="{v}"'
                    cells.append(f'<td class="num"{sort}>{escape(_fmt(v))}</td>')
                else:
                    cells.append(f"<td>{escape(_fmt(v))}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        filt = (
            f'<input class="filter" placeholder="Filter rows" data-target="{tid}" aria-label="Filter">'
            if filterable and len(rows) > 8
            else ""
        )
        return (
            f'{filt}<div class="scroll"><table class="data" id="{tid}"><thead><tr>{head}</tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table></div>"
        )


class _Raw:
    def __init__(self, html: str) -> None:
        self.html = html


def _kpis(items: Sequence[tuple[str, str]]) -> str:
    return (
        '<div class="kpis">'
        + "".join(
            f'<div class="kpi"><div class="v">{escape(v)}</div><div class="l">{escape(label)}</div></div>'
            for label, v in items
        )
        + "</div>"
    )


def _section(sid: str, title: str, body: str) -> str:
    num = next(i for i, (s, _) in enumerate(SECTIONS, 1) if s == sid)
    return f'<section id="{sid}"><h2>{num}. {escape(title)}</h2>{body}</section>'


def _finding_html(f: dict[str, Any]) -> str:
    return (
        f'<div class="finding" data-evidence="{escape(f["evidence"])}">'
        f'<div class="t"><span class="sev-{escape(f["severity"])}">{escape(f["severity"].upper())}</span> '
        f"{escape(f['title'])} "
        f'<span class="tag">{escape(EVIDENCE_LABEL.get(f["evidence"], f["evidence"]))}</span></div>'
        f'<div class="d">{escape(f["detail"])}</div></div>'
    )


def render_html(doc: dict[str, Any], *, max_rows: int = 50) -> str:
    T = _Tables()
    s, meta, a = doc["summary"], doc["metadata"], doc["analyses"]
    status = doc["status"]
    parts: list[str] = []

    top = [f for f in doc["findings"] if f["severity"] != "info" and f["category"] != "rules"][:6]
    parts.append(
        _section(
            "summary",
            "Executive summary",
            _kpis(
                [
                    ("records (union of keys)", f"{s['total_records']:,}"),
                    ("matched", _pct(s["match_percentage"])),
                    ("value mismatches", f"{s['value_mismatch_records']:,}"),
                    ("missing from right", f"{s['missing_right']:,}"),
                    ("missing from left", f"{s['missing_left']:,}"),
                    ("duplicate keys", f"{s['duplicate_keys_left'] + s['duplicate_keys_right']:,}"),
                ]
            )
            + svg.stacked(
                [
                    ("matched", s["matched_records"], svg.OK),
                    ("value mismatch", s["value_mismatch_records"], svg.WARN),
                    ("missing from right", s["missing_right"], svg.BAD),
                    ("missing from left", s["missing_left"], "#7a1f1f"),
                ],
                title="Record status",
            )
            + ("<h3>Key findings</h3>" + "".join(_finding_html(f) for f in top) if top else ""),
        )
    )

    parts.append(
        _section(
            "status",
            "Overall status",
            f'<p><span class="status {STATUS_CLASS[status]}">{escape(STATUS_LABEL[status])}</span></p>'
            '<p class="note">FAIL: at least one error-severity rule broke its threshold. '
            "PASS WITH WARNINGS: no failures, but a warning rule broke its threshold or differences "
            "exist within a configured threshold. PASS: every rule passed with nothing to report. "
            "Defaults allow no missing records and no value mismatches.</p>"
            + T(
                ["Rule", "Outcome", "Severity", "Source", "Observed", "Max", "Min", "Detail"],
                [
                    [
                        r["name"],
                        r["outcome"],
                        r["severity"],
                        r["source"],
                        r["observed"],
                        r["max"],
                        r["min"],
                        r["message"],
                    ]
                    for r in doc["rules"]
                ],
            ),
        )
    )

    parts.append(_section("datasets", "Dataset overview", _datasets(doc, T)))
    parts.append(_section("schema", "Schema differences", _schema(doc, T)))
    parts.append(_section("keys", "Key analysis", _keys(doc, T)))
    parts.append(_section("records", "Record reconciliation", _records(doc, T)))
    parts.append(_section("columns", "Column reconciliation", _columns(doc, T)))
    parts.append(_section("numeric", "Numeric differences", _numeric(doc, T, max_rows)))
    parts.append(_section("distributions", "Distribution differences", _distributions(a, T)))
    parts.append(_section("missing", "Missing records", _missing(doc, T, max_rows)))
    parts.append(
        _section(
            "duplicates",
            "Duplicate keys",
            T(
                list((doc["records"]["duplicate_keys_sample"] or [{}])[0].keys()),
                [list(r.values()) for r in doc["records"]["duplicate_keys_sample"][:max_rows]],
                filterable=True,
                empty="No duplicate keys.",
            ),
        )
    )
    parts.append(
        _section("concentration", "Mismatch concentration", _concentration(a, T, max_rows))
    )
    parts.append(_section("temporal", "Temporal analysis", _temporal(a, T, max_rows)))
    parts.append(
        _section(
            "findings",
            "Findings",
            '<p class="note">Evidence labels: <b>Observed</b> direct measurement; <b>Statistically '
            "supported</b> passed a stated test; <b>Likely explanation</b> a heuristic diagnosis, not "
            "proof; <b>User-configured rule</b> outcome of a configured threshold.</p>"
            + ("".join(_finding_html(f) for f in doc["findings"]) or '<p class="note">None.</p>'),
        )
    )
    recs = doc.get("recommendations") or []
    parts.append(
        _section(
            "recommendations",
            "Recommendations",
            "<ol>" + "".join(f"<li>{escape(r)}</li>" for r in recs) + "</ol>"
            if recs
            else '<p class="note">None.</p>',
        )
    )
    parts.append(_section("reproducibility", "Reproducibility", _repro(doc, T)))

    nav = "".join(
        f'<a href="#{sid}">{i}. {escape(title)}</a>' for i, (sid, title) in enumerate(SECTIONS, 1)
    )
    title = f"ReconSI report: {doc['name']}"
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
        f'<div class="layout"><nav><div class="brand">ReconSI</div>{nav}</nav><main>'
        f'<div class="eyebrow">Reconciliation report</div><h1>{escape(doc["name"])}</h1>'
        f'<p><span class="status {STATUS_CLASS[status]}">{escape(STATUS_LABEL[status])}</span> '
        f'<span class="note">&nbsp;{escape(_source(meta["left"]))} vs {escape(_source(meta["right"]))}'
        f" &middot; keys {escape(', '.join(s['keys']))} &middot; {escape(str(meta.get('started_at', ''))[:19])} UTC</span></p>"
        + "".join(parts)
        + f"</main></div><script>{JS}</script></body></html>"
    )


def _source(d: dict[str, Any]) -> str:
    return str(d.get("name") or d.get("path") or "dataframe")


def _datasets(doc: dict[str, Any], T: _Tables) -> str:
    meta, s, sd = doc["metadata"], doc["summary"], doc["schema"]
    rows = []
    for side in ("left", "right"):
        m = meta[side]
        fp = meta.get(f"{side}_fingerprint") or {}
        rows.append(
            [
                side,
                m.get("name"),
                m.get("format"),
                s[f"{side}_rows"],
                s[f"{side}_records"],
                sd[side]["column_count"],
                (fp.get("digest") or "")[:16],
            ]
        )
    notes = "".join(f"<li>{escape(n['message'])}</li>" for n in doc.get("notes", []))
    return T(
        ["Side", "Name", "Format", "Rows", "Records compared", "Columns", "Fingerprint"], rows
    ) + (f"<h3>Processing notes</h3><ul>{notes}</ul>" if notes else "")


def _schema(doc: dict[str, Any], T: _Tables) -> str:
    sd = doc["schema"]
    out = [
        f"<p>Left has {sd['left']['column_count']} columns, right has {sd['right']['column_count']}. "
        f"Column order {'differs' if sd['order_changed'] else 'is the same'}.</p>"
    ]
    if sd["identical"]:
        out.append('<p class="note">The schemas are identical.</p>')
    changes = [
        [k, ", ".join(sd[f"{k}_columns"])] for k in ("added", "removed") if sd[f"{k}_columns"]
    ]
    if sd["renamed_columns"]:
        renamed = ", ".join(f"{a} -> {b}" for a, b in sd["renamed_columns"].items())
        changes.append(["renamed (configured)", renamed])
    out.append(T(["Change", "Columns"], changes, empty="No added, removed or renamed columns."))
    if sd["dtype_changes"]:
        out.append("<h3>Type changes</h3>")
        out.append(
            T(
                ["Column", "Left", "Right", "Compatible"],
                [
                    [c["column"], c["left_dtype"], c["right_dtype"], c["compatible"]]
                    for c in sd["dtype_changes"]
                ],
            )
        )
    if sd["suggested_column_matches"]:
        out.append("<h3>Suggested column matches (not applied)</h3>")
        out.append(
            T(
                ["Left", "Right", "Score", "Name", "Type", "Value overlap"],
                [
                    [
                        m["left"],
                        m["right"],
                        m["score"],
                        m["signals"].get("name"),
                        m["signals"].get("type"),
                        m["signals"].get("value_overlap"),
                    ]
                    for m in sd["suggested_column_matches"]
                ],
            )
        )
    return "".join(out)


def _keys(doc: dict[str, Any], T: _Tables) -> str:
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
                p["rows_in_duplicate_keys"],
                p["max_multiplicity"],
                p["mean_records_per_key"],
                p["null_keys"],
            ]
        )
    out = [
        f"<p>Relationship <b>{escape(k['relationship'])}</b>. {k['common_keys']:,} keys on both sides, "
        f"{k['left_only_keys']:,} only left, {k['right_only_keys']:,} only right. A naive join on these "
        f"keys would produce {k['naive_join_rows']:,} rows ({k['join_inflation']:,} more than the common keys).</p>",
        T(
            [
                "Side",
                "Rows",
                "Unique keys",
                "Duplicated keys",
                "Rows in duplicated keys",
                "Max rows/key",
                "Mean rows/key",
                "Null keys",
            ],
            rows,
        ),
    ]
    for side in ("left", "right"):
        dist = k[side]["multiplicity_distribution"]
        if len(dist) > 1:
            out.append(f"<h3>Rows per key ({side})</h3>")
            out.append(svg.hbar(list(dist.items()), title=f"Rows per key, {side}"))
    issues = []
    for side in ("left", "right"):
        for col, fi in k[side]["format_issues"].items():
            if any(
                fi[x]
                for x in ("blank", "whitespace", "case_variants", "leading_zeros", "malformed")
            ):
                issues.append(
                    [
                        side,
                        col,
                        fi["blank"],
                        fi["whitespace"],
                        fi["case_variants"],
                        fi["leading_zeros"],
                        fi["malformed"],
                        fi["dominant_pattern"],
                    ]
                )
    if issues:
        out.append("<h3>Key formatting</h3>")
        out.append(
            T(
                [
                    "Side",
                    "Column",
                    "Blank",
                    "Whitespace",
                    "Case variants",
                    "Leading zeros",
                    "Malformed",
                    "Dominant pattern",
                ],
                issues,
            )
        )
    if k["normalization_diagnosis"]:
        out.append("<h3>Would unmatched keys match after normalisation? (diagnostic only)</h3>")
        out.append(
            T(
                ["Normalisation", "Would match", "Share of left-only keys", "Examples"],
                [
                    [
                        d["normalization"],
                        d["would_match"],
                        _pct(100 * d["share_of_left_only"]),
                        ", ".join(d["examples"]),
                    ]
                    for d in k["normalization_diagnosis"]
                ],
            )
        )
    return "".join(out)


def _records(doc: dict[str, Any], T: _Tables) -> str:
    s = doc["summary"]
    a = doc["analyses"]
    rows = [
        ["Matched", s["matched_records"], s["match_percentage"]],
        ["Value mismatch", s["value_mismatch_records"], None],
        ["Missing from right (left only)", s["missing_right"], None],
        ["Missing from left (right only)", s["missing_left"], None],
        ["Ambiguous (set aside)", s["ambiguous_records"], None],
    ]
    out = T(["Status", "Records", "Match %"], rows)
    totals = (a.get("control_totals") or {}).get("columns") or {}
    if totals:
        out += "<h3>Control totals (all rows, before matching)</h3>" + T(
            ["Column", "Left sum", "Right sum", "Difference", "Relative difference"],
            [
                [
                    c,
                    t["left_sum"],
                    t["right_sum"],
                    t["difference"],
                    _pct(
                        None
                        if t["relative_difference"] is None
                        else 100 * t["relative_difference"],
                        4,
                    ),
                ]
                for c, t in totals.items()
            ],
        )
    grain = a.get("grain")
    if grain:
        out += (
            "<h3>Grain (inferred)</h3>"
            f"<p>Left appears to be at <b>{escape(grain['left']['description'])}</b>; right appears to "
            f"be at <b>{escape(grain['right']['description'])}</b>. "
            '<span class="note">Inferred from observed uniqueness; not a guarantee.</span></p>'
        )
    diag = a.get("aggregation_diagnosis")
    if diag:
        out += f"<h3>Aggregation diagnosis</h3><p>{escape(diag['conclusion'])}</p>" + T(
            [
                "Column",
                "Keys compared",
                "Keys matching after aggregation",
                "Left total",
                "Right total",
            ],
            [
                [
                    c,
                    diag["keys_compared"],
                    v["keys_matching_after_aggregation"],
                    v["left_total"],
                    v["right_total"],
                ]
                for c, v in diag["columns"].items()
            ],
        )
    return out


def _columns(doc: dict[str, Any], T: _Tables) -> str:
    cols = list(doc["columns"].values())
    chart = svg.hbar(
        [
            (c["column"], c["mismatch_percentage"])
            for c in sorted(cols, key=lambda c: -c["mismatch_percentage"])
        ],
        value_format="percent",
        color=svg.WARN,
        title="Mismatch rate by column",
    )
    rows = [
        [
            c["column"],
            c["kind"],
            c["classification"].replace("_", " "),
            c["compared"],
            c["mismatches"],
            c["match_percentage"],
            f"{c['mismatch_percentage_ci95'][0]:.2f}-{c['mismatch_percentage_ci95'][1]:.2f}%",
            c["within_tolerance"],
            c["null_mismatches"],
            ", ".join(f"{k}={v}" for k, v in c["mismatch_types"].items()),
        ]
        for c in cols
    ]
    return (
        "<h3>Mismatch rate by column</h3>" + chart if any(c["mismatches"] for c in cols) else ""
    ) + T(
        [
            "Column",
            "Kind",
            "Classification",
            "Compared",
            "Mismatches",
            "Match %",
            "Mismatch 95% CI",
            "Within tolerance",
            "Null mismatches",
            "Types",
        ],
        rows,
        filterable=True,
        empty="No columns were compared.",
    )


def _numeric(doc: dict[str, Any], T: _Tables, max_rows: int) -> str:
    out = []
    a = doc["analyses"]
    for c in doc["columns"].values():
        if c["kind"] != "numeric" or not c["mismatches"]:
            continue
        col = c["column"]
        d = c["mismatch_differences"] or {}
        out.append(f"<h3>{escape(col)}</h3>")
        hist = c.get("mismatch_histogram")
        if hist:
            out.append(svg.histogram(hist["counts"], hist["edges"], title=f"Differences in {col}"))
        out.append(
            T(
                ["Statistic (right - left, mismatches)", "Value"],
                [
                    [k, d.get(k)]
                    for k in (
                        "count",
                        "mean",
                        "median",
                        "std",
                        "min",
                        "p05",
                        "p25",
                        "p75",
                        "p95",
                        "max",
                        "mean_absolute",
                        "positive",
                        "negative",
                    )
                ],
            )
        )
        bias = (a.get("bias") or {}).get(col) or {}
        if bias.get("systematic"):
            out.append(f'<p class="warn">{escape(bias["message"])}</p>')
        elif bias.get("tested"):
            out.append(
                f'<p class="note">No systematic direction: {bias["positive"]:,} higher, {bias["negative"]:,} '
                f"lower on the right (sign test p={bias['sign_test_p_value']:.2g}).</p>"
            )
        largest = (a.get("largest_differences") or {}).get(col) or {}
        if largest.get("absolute"):
            rows = largest["absolute"][:max_rows]
            headers = [h for h in rows[0] if h != "column"]
            out.append("<p><b>Largest absolute differences</b></p>")
            out.append(T(headers, [[r.get(h) for h in headers] for r in rows]))
    return "".join(out) or '<p class="note">No numeric mismatches.</p>'


def _distributions(a: dict[str, Any], T: _Tables) -> str:
    dist = (a.get("distributions") or {}).get("columns") or {}
    rows = []
    for col, d in dist.items():
        if not d.get("tested"):
            continue
        if d["type"] == "numeric":
            rows.append(
                [
                    col,
                    "numeric",
                    d["left"]["mean"],
                    d["right"]["mean"],
                    d["left"]["median"],
                    d["right"]["median"],
                    f"KS {d['ks_statistic']:.3f}",
                    d["ks_p_value"],
                    f"Wasserstein {d['wasserstein_distance']:.4g}",
                    d["shift"],
                ]
            )
        else:
            rows.append(
                [
                    col,
                    "categorical",
                    None,
                    None,
                    None,
                    None,
                    f"chi2 {d['chi_square']:.4g}",
                    d["chi_square_p_value"],
                    f"JSD {d['jensen_shannon_divergence']:.4f}",
                    d["shift"],
                ]
            )
    sampled = (a.get("distributions") or {}).get("sampled")
    note = (
        '<p class="note">Compares each column across the two datasets without matching rows. A shift '
        "requires p &lt; alpha and a practical effect size (KS &ge; 0.1 or |SMD| &ge; 0.2; JSD &ge; 0.02 or "
        "Cram&eacute;r's V &ge; 0.1). Tests assume independent observations."
        + (" Computed on a seeded random sample." if sampled else "")
        + "</p>"
    )
    return note + T(
        [
            "Column",
            "Type",
            "Left mean",
            "Right mean",
            "Left median",
            "Right median",
            "Statistic",
            "p-value",
            "Effect",
            "Shift",
        ],
        rows,
    )


def _missing(doc: dict[str, Any], T: _Tables, max_rows: int) -> str:
    out = []
    rec = doc["records"]
    for title, key in (
        ("Missing from right (present only in left)", "missing_right_sample"),
        ("Missing from left (present only in right)", "missing_left_sample"),
    ):
        rows = rec.get(key) or []
        out.append(f"<h3>{escape(title)}</h3>")
        if rows:
            headers = list(rows[0].keys())
            out.append(
                T(headers, [[r.get(h) for h in headers] for r in rows[:max_rows]], filterable=True)
            )
        else:
            out.append('<p class="note">None.</p>')
    pop = doc["analyses"].get("unmatched_population") or {}
    for label, data in pop.items():
        sig = [d for d in data["dimensions"] if d["significant"]]
        if not sig:
            continue
        out.append(f"<h3>Who is {escape(label.replace('_', ' '))}?</h3>")
        out.append(
            T(
                [
                    "Dimension",
                    "Over-represented level",
                    "Share of missing",
                    "Share of matched",
                    "Bonferroni p",
                ],
                [
                    [
                        d["dimension"],
                        d["over_represented"][0]["level"] if d["over_represented"] else "",
                        _pct(100 * d["over_represented"][0]["share_of_missing"], 1)
                        if d["over_represented"]
                        else "",
                        _pct(100 * d["over_represented"][0]["share_of_present"], 1)
                        if d["over_represented"]
                        else "",
                        d["p_value_bonferroni"],
                    ]
                    for d in sig
                ],
            )
        )
    return "".join(out)


def _concentration(a: dict[str, Any], T: _Tables, max_rows: int) -> str:
    conc = a.get("concentration") or []
    if not conc:
        return '<p class="note">No categorical dimensions were available.</p>'
    out = []
    for entry in conc:
        dim = entry["dimension"]
        flag = " (concentrated)" if entry["concentrated"] else ""
        out.append(f"<h3>{escape(dim)}{escape(flag)}</h3>")
        if entry.get("message"):
            out.append(f"<p>{escape(entry['message'])}</p>")
        levels = entry["levels"][:15]
        out.append(
            svg.hbar(
                [(str(lv[dim]), 100 * lv["problem_rate"]) for lv in levels],
                value_format="percent",
                color=svg.WARN,
                title=f"Problem rate by {dim}",
            )
        )
        out.append(
            T(
                [
                    dim,
                    "Records",
                    "Matched",
                    "Value mismatch",
                    "Missing left",
                    "Missing right",
                    "Problem rate",
                    "Share of problems",
                    "Lift",
                ],
                [
                    [
                        lv[dim],
                        lv["records"],
                        lv["matched"],
                        lv["value_mismatch"],
                        lv["missing_left"],
                        lv["missing_right"],
                        _pct(100 * lv["problem_rate"]),
                        _pct(100 * lv["share_of_problems"], 1),
                        lv["lift"],
                    ]
                    for lv in entry["levels"][:max_rows]
                ],
            )
        )
    return "".join(out)


def _temporal(a: dict[str, Any], T: _Tables, max_rows: int) -> str:
    t = a.get("temporal")
    if not t:
        return '<p class="note">No date column was found (set <code>date_column</code>).</p>'
    periods = t["periods"]
    labels = [str(p["period"])[:10] for p in periods]
    anomalies = {str(x["period"])[:10] for x in t["anomalous_periods"]}
    chart = svg.line(
        labels,
        [100 * p["match_rate"] for p in periods],
        markers=[int(cp["index"]) for cp in t["change_points"]],
        highlights=[i for i, label in enumerate(labels) if label in anomalies],
        y_label="match %",
        title="Match rate over time",
    )
    out = [chart]
    for cp in t["change_points"]:
        out.append(f'<p class="warn">{escape(cp["message"])}</p>')
    if t["anomalous_periods"]:
        out.append(
            T(
                ["Anomalous period", "Problem rate", "Baseline rate", "Bonferroni p"],
                [
                    [
                        str(x["period"])[:10],
                        _pct(100 * x["problem_rate"]),
                        _pct(100 * x["baseline_rate"]),
                        x["p_value_bonferroni"],
                    ]
                    for x in t["anomalous_periods"]
                ],
            )
        )
    out.append(
        T(
            ["Period", "Records", "Match %", "Value mismatch", "Missing left", "Missing right"],
            [
                [
                    str(p["period"])[:10],
                    p["records"],
                    100 * p["match_rate"],
                    p["value_mismatch"],
                    p["missing_left"],
                    p["missing_right"],
                ]
                for p in periods[-max_rows * 4 :]
            ],
            filterable=True,
        )
    )
    return "".join(out)


def _repro(doc: dict[str, Any], T: _Tables) -> str:
    meta = doc["metadata"]
    rows = [
        ["ReconSI version", meta.get("reconsi_version")],
        ["Python", meta.get("python_version")],
        ["Platform", meta.get("platform")],
        ["Started (UTC)", meta.get("started_at")],
        ["Duration (s)", meta.get("duration_seconds")],
        ["Backend", meta.get("backend")],
        ["Seed", meta.get("seed")],
        ["Git commit", meta.get("git_commit")],
        ["Configuration hash", meta.get("config_hash")],
        ["Left fingerprint", (meta.get("left_fingerprint") or {}).get("digest")],
        ["Right fingerprint", (meta.get("right_fingerprint") or {}).get("digest")],
        ["Run ID", meta.get("run_id")],
    ]
    return T(["Item", "Value"], [[k, "" if v is None else str(v)] for k, v in rows])
