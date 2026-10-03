# Examples

Seven complete scenarios live in [`examples/`](../examples). Each generates its own data, runs
ReconSI and writes a report to `examples/output/` (git-ignored). Run one with
`python examples/01_csv_reports.py`, or all with `python scripts/run_examples.py`.

| # | Scenario | What it shows |
|---|---|---|
| 1 | [Two CSV reports](../examples/01_csv_reports.py) | Rounded revenue and a dropped store: tolerance absorbs the rounding, the unmatched-population analysis points at store `S017` |
| 2 | [Finance reconciliation](../examples/02_finance.py) | Ledger transactions vs a monthly summary per account; one account-month off by 412.50 |
| 3 | [Sales systems](../examples/03_sales_systems.py) | Different column names (suggested, then confirmed), upper-cased names compared case-insensitively |
| 4 | [Aggregated vs raw](../examples/04_aggregated_vs_raw.py) | Naive comparison vs grain-aware comparison; the aggregation diagnosis; three orders missing from one daily count |
| 5 | [Database exports](../examples/05_database_exports.py) | Parquet snapshots via a YAML job: schema changes, a column-match suggestion, a +05:30 timezone bug, evidence export, history |
| 6 | [Time-based reconciliation](../examples/06_time_based.py) | A four-day incident located by change-point detection |
| 7 | [Duplicate key problem](../examples/07_duplicate_keys.py) | How a many-to-many join turns two totals of 210 into 370, and how aggregation fixes it |

Excerpt from example 7:

```text
order total: 210.0 shipment total: 210.0
total after a naive join: 370.0 (13 joined rows)
Mean records per key: left 2.00, right 2.00. A naive join on order_id would produce 13 rows
for 3 common keys (10 extra), inflating any totals computed from it.
```

Excerpt from example 6:

```text
Problem rate changed significantly around 2026-09-14 (0.17% before, 25.01% after). This identifies when, not why.
Problem rate changed significantly around 2026-09-18 (25.01% before, 0.29% after). This identifies when, not why.
injected incident: ('2026-09-14', '2026-09-18')
```
