# ReconSI

**Reconciliation Intelligence. Find out why your numbers don't match.**

[![CI](https://github.com/Yashjindal11/reconsi/actions/workflows/ci.yml/badge.svg)](https://github.com/Yashjindal11/reconsi/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Two systems, reports or extracts are supposed to describe the same business reality, and they
don't agree. ReconSI is a local-first Python toolkit and CLI that compares them and explains the
difference with evidence:

- what matches, what doesn't, and by how much;
- which records are missing or extra, and whether the missing ones share a profile;
- whether keys are duplicated, null, malformed, differently typed or differently formatted;
- which columns differ, in which direction, and whether the direction is **systematic**;
- whether the "mismatch" is really a **grain** problem (transactions vs. a daily summary);
- where problems **concentrate** (region, product, channel) and **when** they started.

No LLMs, no API keys, no network access. Same inputs and configuration, same answer.

## Install

```bash
pip install reconsi                  # pandas backend; CSV and JSON
pip install "reconsi[parquet]"       # + Parquet
pip install "reconsi[duckdb]"        # + DuckDB backend
pip install "reconsi[all]"           # + Parquet, DuckDB, matplotlib charts
```

## Two files, one command

```bash
reconsi compare sales_a.csv sales_b.parquet --keys order_id
```

```text
ReconSI  reconciliation
Status   FAIL

  left rows                  50,000
  right rows                 49,600
  matched                    49,000  (97.80%)
  value mismatches              500  (1.01% of compared)
  missing from right            500
  missing from left             100
  duplicate keys            0 left / 0 right

Columns with mismatches:
  revenue                        153  0.31%  numeric_mismatch
  updated_at                     150  0.30%  datetime_mismatch
  customer                       100  0.20%  string_mismatch
  quantity                        57  0.12%  numeric_mismatch
  status                          40  0.08%  string_mismatch

Findings:
  [warning/observed] 500 records in the left dataset are missing from the right dataset
  [warning/observed] 100 records in the right dataset are missing from the left dataset
  [warning/observed] 500 matched records have differing values
  [warning/likely] customer: 100 of 100 string mismatches are formatting only
  [warning/likely] updated_at: timestamps differ by a constant +05:30
  ... 

wrote reconsi-report.html
```

The HTML report is a single offline file: executive summary, rules, schema and key analysis,
column statistics, difference histograms, systematic bias, distribution tests, missing-record
profiles, duplicate keys, mismatch concentration, a reconciliation timeline with change points,
findings and recommendations. Markdown, JSON and CSV/Parquet evidence exports are one flag away.

## In Python

```python
import pandas as pd
from reconsi import reconcile

a = pd.DataFrame({"id": [1, 2, 3], "country": ["India", "USA", "UK"], "amount": [100, 200, 300]})
b = pd.DataFrame({"id": [1, 2, 4], "country": ["India", "USA", "Canada"], "amount": [100, 250, 400]})

result = reconcile(a, b, keys=["id"])
print(result)
# <ReconciliationResult FAIL: 1 matched, 1 value mismatches, 1 missing left, 1 missing right>

print(result.value_mismatches[["id", "column", "left_value", "right_value", "difference"]])
for finding in result.findings[:4]:
    print(f"[{finding.evidence.value}] {finding.title}")
```

Transactions against a daily summary:

```python
transactions = pd.DataFrame(
    {"date": ["2026-10-01"] * 3 + ["2026-10-02"] * 2, "revenue": [100.0, 50.0, 25.0, 10.0, 15.0]}
)
daily = pd.DataFrame({"date": ["2026-10-01", "2026-10-02"], "revenue": [175.0, 30.0], "orders": [3, 2]})

result = reconcile(
    transactions,
    daily,
    left_group_by=["date"],
    aggregations={"revenue": "sum", "orders": "count"},
)
print(result.value_mismatches[["date", "column", "left_value", "right_value"]])
# 2026-10-02  revenue  25.0  30.0
```

## What it does

| Area | Highlights |
|---|---|
| Inputs | DataFrames, CSV/TSV, Parquet, JSON/JSONL, Arrow/Polars via `to_pandas()`; key columns read as text so `00123` survives |
| Keys | uniqueness, multiplicity, nulls, blanks, whitespace, case variants, leading zeros, malformed patterns, type differences, naive-join inflation, "would match after normalisation" diagnosis |
| Duplicates | `strict`, `first`, `last`, `aggregate`, `grouped`, `multiset` strategies |
| Values | symmetric numeric tolerance (absolute/relative, per column), exact big-integer comparison, explicit string normalisation, timezone-aware datetime comparison with tolerance, explicit null semantics, column mapping |
| Schema | added / removed / retyped / reordered columns, nullability; column-match **suggestions** (never applied) |
| Grain | `left_group_by` / `right_group_by` reconciliation, grain inference, aggregation diagnosis, control totals |
| Statistics | difference distributions, Wilson intervals, sign-test bias detection, KS / Wasserstein / chi-square / Jensen-Shannon distribution comparison, chi-square concentration with drill-down, unmatched-population profiling |
| Time | match rate per day/week/month, circular binary segmentation change points, regime-relative anomaly detection |
| Judgement | rules, thresholds, column-level limits and critical columns; explicit PASS / PASS_WITH_WARNINGS / FAIL |
| Output | HTML, Markdown, versioned JSON, CSV/Parquet/JSON evidence, matplotlib helpers |
| Operations | YAML jobs, CLI with CI-friendly exit codes, dataset fingerprints, SQLite run history, run diff, DuckDB backend |

Every finding is labelled **observed**, **statistically supported**, **likely explanation** or
**user-configured rule**. ReconSI never presents a heuristic as a fact and never claims a cause.

## Evidence that it works

- [Evaluation](docs/evaluation.md): 12 ground-truth scenarios x 5 seeds (missing and extra
  records, value errors, duplicates, rounding with and without tolerance, timezone shifts,
  formatting, segment-level bias, segment-level data loss, a time-boxed incident, a grain
  difference). Every injected record, cell and duplicate key was found with no false positives;
  these scenarios are unambiguous by construction, so they test correctness, not sensitivity.
- [Research notes](docs/research.md): where the diagnostics stop working. The bias detector
  flags pure systematic shifts from 10 differing pairs and stays at or below its 1% false-positive
  level on random noise; a segment with twice the base problem rate is identified in 84% of
  trials at 20,000 records, a 1.5x segment in only 7%.
- [Scaling](docs/large-datasets.md), measured on an Apple M4 MacBook Air (16 GB), single runs:

  | Rows per side | pandas | DuckDB |
  |---|---|---|
  | 100,000 | 1.2 s | 1.7 s |
  | 1,000,000 | 6.2 s | 8.4 s |
  | 10,000,000 | 88 s, 4.7 GB peak | 76 s, 6.0 GB peak |

## Documentation

[Quickstart](docs/quickstart.md) · [Concepts](docs/concepts.md) ·
[Keys and duplicates](docs/keys-and-duplicates.md) · [Value comparison](docs/value-comparison.md) ·
[Schema](docs/schema.md) · [Aggregation and grain](docs/aggregation.md) ·
[Statistics](docs/statistics.md) · [Rules](docs/rules.md) · [Reports](docs/reports.md) ·
[JSON schema](docs/json-schema.md) · [Configuration](docs/configuration.md) · [CLI](docs/cli.md) ·
[Python API](docs/python-api.md) · [Large datasets](docs/large-datasets.md) ·
[Extending](docs/extending.md) · [Examples](docs/examples.md) · [FAQ](docs/faq.md)

## Limitations

- Comparison runs in Python on the joined rows for both backends; the DuckDB backend moves
  loading, de-duplication, aggregation and the join out of core but does not yet push
  comparisons into SQL.
- Statistical tests assume independent records; autocorrelation in time series is not modelled.
- Concentration is tested one dimension at a time; combinations are available through
  `drill_down` but not tested automatically.
- SQL sources are not read directly: run queries yourself and pass DataFrames.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
