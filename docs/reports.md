# Reports

All reports are rendered from the same JSON document (`result.to_dict()`), so a saved result can
be re-rendered later: `reconsi report result.json -o report.html`.

## HTML

`result.to_html("report.html")` writes a single self-contained file: inline CSS, inline SVG
charts and a few lines of JavaScript for sortable, filterable tables. It loads nothing from the
network and works offline. Sections:

1. Executive summary (key figures, record status bar, key findings)
2. Overall status (every rule result)
3. Dataset overview (sources, row counts, fingerprints, processing notes)
4. Schema differences
5. Key analysis (uniqueness, multiplicity, formatting, normalisation diagnosis)
6. Record reconciliation (status counts, control totals, inferred grain, aggregation diagnosis)
7. Column reconciliation (mismatch rate by column with confidence intervals)
8. Numeric differences (histograms, statistics, systematic bias, largest differences)
9. Distribution differences
10. Missing records (samples, unmatched population)
11. Duplicate keys
12. Mismatch concentration (per dimension)
13. Temporal analysis (match rate over time, change points, anomalous periods)
14. Findings (with evidence labels)
15. Recommendations
16. Reproducibility

Data values are HTML-escaped. Reports contain samples of your data (up to `sample_size` rows per
table, default 20): treat them with the same care as the data.

## Markdown

`result.to_markdown("report.md")` produces GitHub-flavoured Markdown suitable for pull requests,
wikis and tickets: summary table, findings with evidence labels, recommendations, rules, schema,
keys, columns, statistics and samples.

## JSON

`result.to_json("result.json")` writes the stable document described in
[json-schema.md](json-schema.md). It is strict JSON (no `NaN`/`Infinity`).

## Evidence exports

```py
files = result.export("evidence/", formats=["csv", "parquet"])
```

writes `missing_left`, `missing_right`, `value_mismatches`, `ambiguous`, `duplicate_keys`,
`column_statistics` and `records` (the status of every key) in each format, plus `result.json`.
File names are fixed; nothing is derived from data values.

## Charts in notebooks

With `pip install "reconsi[report]"`:

```py
from reconsi.visualization import plots

plots.plot_record_status(result)
plots.plot_column_mismatches(result)
plots.plot_difference_distribution(result, "revenue")
plots.plot_timeline(result)
plots.plot_concentration(result, "region")
plots.plot_duplicate_distribution(result)
```
