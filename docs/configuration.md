# Configuration reference

The same options are accepted as YAML (`reconsi run job.yaml`), as keyword arguments
(`reconcile(left, right, **options)`) and as a `ReconConfig` object. YAML is parsed with
`yaml.safe_load` and validated before anything runs (`reconsi validate job.yaml`); unknown
fields are errors.

## Datasets

```yaml
left:
  path: data/system_a.parquet      # relative to the YAML file
  format: parquet                  # optional: csv, parquet, json, jsonl, excel (from suffix by default)
  read_options: {sep: ";"}         # an allow-list of reader options per format
right:
  path: data/system_b.csv
```

Only local files are accepted (no URLs). Reader options are restricted to an allow-list
(`sep`, `encoding`, `decimal`, `thousands`, `header`, `skiprows`, `nrows`, `na_values`,
`keep_default_na`, `quotechar`, `comment`, `usecols`, `dtype` for CSV; `columns` for Parquet;
`orient`, `encoding`, `dtype` for JSON).

## Keys and columns

| Option | Default | Meaning |
|---|---|---|
| `keys` | required | key columns (left names) |
| `left_keys` / `right_keys` | `keys` | key columns per side, same order |
| `column_mapping` | `{}` | `left_name: right_name` |
| `compare_columns` | all common non-key columns | columns to compare |
| `exclude_columns` | `[]` | columns never compared |
| `key_normalize` | `[]` | normalisation applied to key values before matching |

## Comparison

`defaults` apply to every column, `columns.<name>` override them, and named `rules` with a
`column` override both.

| Option | Default | Meaning |
|---|---|---|
| `type` | `auto` | `numeric`, `string`, `datetime`, `boolean` |
| `absolute_tolerance` | `0` | numeric |
| `relative_tolerance` | `0` for integers, `1e-9` for floats | numeric |
| `decimals` | none | round both sides before comparing |
| `normalize` | `[]` | `trim`, `lowercase`, `casefold`, `collapse_whitespace`, `unicode_nfc`, `unicode_nfkc`, `strip_leading_zeros` |
| `timezone` | none | IANA zone for naive timestamps |
| `tolerance_seconds` | `0` | datetime tolerance |
| `compare_as_date` | `false` | compare calendar dates only |
| `null_equals_null` | `true` | |
| `empty_string_as_null` | `false` | |
| `critical` | `false` | any mismatch fails the run |
| `max_mismatch_percentage`, `max_mismatches` | none | column thresholds |

Shorthand: `tolerances: {revenue: {absolute: 0.01, relative: 0.0001}}`.

## Duplicates and grain

| Option | Default | Meaning |
|---|---|---|
| `duplicate_strategy` | `strict` | `strict`, `first`, `last`, `aggregate`, `grouped`, `multiset` |
| `aggregations` | `{}` | `column: sum / count / size / mean / median / min / max / first / last / nunique` |
| `left_group_by` / `right_group_by` | none | aggregate that side to these columns first (they become the keys) |

## Analysis

| Option | Default | Meaning |
|---|---|---|
| `dimensions` | auto-detected | columns for concentration analysis |
| `max_dimensions` | `8` | |
| `max_dimension_levels` | `50` | |
| `date_column` | auto-detected | column for temporal analysis |
| `time_frequency` | `D` | `D`, `W` or `M` |
| `alpha` | `0.01` | significance level for all tests |
| `distribution_sample` | `200000` | rows per side for distribution tests |
| `seed` | `0` | seed for every sample and permutation test |
| `suggest_columns` | `true` | compute column-match suggestions |

## Rules and thresholds

See [rules](rules.md): `thresholds` (`max_missing_records`, `max_missing_percentage`,
`max_mismatched_records`, `max_mismatch_percentage`, `max_duplicate_keys`, `max_schema_changes`)
and `rules` (named rules). The shorthand `rules: {max_mismatch_percentage: 0.1}` (a mapping instead
of a list) is read as thresholds.

## Execution and output

| Option | Default | Meaning |
|---|---|---|
| `name`, `description` | `reconciliation` | |
| `backend` | `pandas` | or `duckdb` |
| `backend_options` | `{}` | DuckDB: `memory_limit`, `threads`, `temp_directory` |
| `chunk_size` | `1000000` | joined rows compared per chunk |
| `sample_size` | `20` | sample rows per table in reports and JSON |
| `max_detail_rows` | `1000000` | cap on retained mismatch / missing rows (counts stay exact) |
| `output` | none | `html`, `json`, `markdown`, `export_dir` (must stay inside the YAML file's directory) |
| `history` | none | `{path: .reconsi/history.db, enabled: true}` |

## A complete example

```yaml
name: finance_monthly_close
description: General ledger vs. bank transactions
left: {path: data/ledger.parquet}
right: {path: data/bank.csv, read_options: {sep: ";"}}
keys: [transaction_id]
column_mapping: {amount: amt, booked_on: value_date}
defaults: {normalize: [trim]}
columns:
  amount: {type: numeric, absolute_tolerance: 0.005, critical: true}
  booked_on: {type: datetime, compare_as_date: true}
duplicate_strategy: strict
dimensions: [account, currency]
date_column: booked_on
thresholds:
  max_missing_records: 0
rules:
  - {name: counterparty_names, column: counterparty, normalize: [trim, casefold], max: 5, severity: warning}
output: {html: out/close.html, json: out/close.json, export_dir: out/evidence}
history: {path: .reconsi/history.db}
```
