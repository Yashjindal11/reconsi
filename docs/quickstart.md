# Quickstart

## Install

```bash
pip install reconsi                 # pandas backend, CSV / JSON input
pip install "reconsi[parquet]"      # + Parquet
pip install "reconsi[duckdb]"       # + DuckDB backend (includes Parquet)
pip install "reconsi[report]"       # + matplotlib plotting helpers
pip install "reconsi[all]"          # everything
```

Python 3.11 or newer. HTML, Markdown and JSON reports need no extra packages.

## Two CSV files, one command

```bash
reconsi compare sales_a.csv sales_b.csv --keys customer_id
```

This prints a summary, writes `reconsi-report.html` and exits with code 1 if the
reconciliation fails (use `--fail-on never` to always exit 0). Add `--json result.json`,
`--markdown report.md` or `--export-dir evidence/` for other outputs.

## In Python

```python
import pandas as pd
from reconsi import reconcile

left = pd.DataFrame(
    {"customer_id": [1, 2, 3], "country": ["India", "USA", "UK"], "revenue": [100.0, 200.0, 300.0]}
)
right = pd.DataFrame(
    {"customer_id": [1, 2, 4], "country": ["India", "USA", "Canada"], "revenue": [100.0, 250.0, 400.0]}
)

result = reconcile(left, right, keys=["customer_id"], compare_columns=["revenue"])

print(result.status)                       # FAIL
print(result.summary["matched_records"])   # 1
print(result.summary["missing_right"])     # 1  (customer 3 is only in the left dataset)
print(result.summary["missing_left"])      # 1  (customer 4 is only in the right dataset)
print(result.value_mismatches[["customer_id", "column", "left_value", "right_value", "difference"]])
```

`result` answers the usual questions directly:

```python
result.matched              # keys of fully matching records
result.missing_right        # full rows present only on the left
result.missing_left         # full rows present only on the right
result.value_mismatches     # one row per differing cell
result.duplicate_keys       # every duplicated key with its count on each side
result.column_statistics    # per-column match counts and difference statistics
for finding in result.findings[:5]:
    print(finding.severity.value, finding.evidence.value, finding.title)
```

And produces reports:

```py
result.to_html("report.html")
result.to_markdown("report.md")
result.to_json("result.json")
result.export("evidence/", formats=["csv", "parquet"])
```

## A YAML job

```yaml
name: daily_sales_reconciliation
left:
  path: sales_system_a.parquet
right:
  path: sales_system_b.parquet
keys: [date, store_id, product_id]
columns:
  revenue: {type: numeric, absolute_tolerance: 0.01}
  quantity: {type: numeric, absolute_tolerance: 0}
thresholds:
  max_mismatch_percentage: 0.1
output:
  html: reports/daily.html
  json: reports/daily.json
history:
  path: .reconsi/history.db
```

```bash
reconsi validate job.yaml
reconsi run job.yaml
reconsi history
```

Next: [core concepts](concepts.md).
