# Python API

## `reconcile`

```py
reconcile(left, right, keys=None, compare_columns=None, **options) -> ReconciliationResult
```

`left` / `right`: a pandas DataFrame, a path to a CSV / TSV / Parquet / JSON / JSON Lines file,
or any object with `to_pandas()` (a PyArrow table, a Polars DataFrame). `options` are any
[configuration](configuration.md) fields. The shortcuts `absolute_tolerance`,
`relative_tolerance`, `decimals`, `normalize`, `timezone`, `tolerance_seconds`,
`compare_as_date`, `null_equals_null` and `empty_string_as_null` apply to every column.

## `Reconciliation`

A reusable job:

```python
import pandas as pd
from reconsi import ReconConfig, Reconciliation

left = pd.DataFrame({"id": [1, 2, 3], "amount": [10.0, 20.0, 30.0]})
right = pd.DataFrame({"id": [1, 2, 3], "amount": [10.0, 20.5, 30.0]})

job = Reconciliation(left=left, right=right, keys=["id"])
result = job.run()

config = ReconConfig(keys=["id"], thresholds={"max_mismatch_percentage": 50})
result = Reconciliation(left, right, config=config).run()
print(result.status)
```

`Reconciliation(config=..., base_dir=...)` without frames reads `left.path` / `right.path` from
the configuration, relative to `base_dir`. `reconsi.load_config(path)` loads a YAML job.

## `ReconciliationResult`

```python
result.summary["match_percentage"]
result.column_statistics            # DataFrame, one row per column
result.largest_differences("amount", n=5, by="absolute")   # or relative / positive / negative
result.record_mismatches(limit=10)  # list[RecordMismatch]
doc = result.to_dict()              # the JSON document
```

`RecordMismatch` has `key`, `column`, `left_value`, `right_value`, `difference`,
`relative_difference`, `mismatch_type`.

`drill_down(dimension, *more, where=None)` breaks record status down by dimensions (see
[statistics](statistics.md)). Outputs: `to_json(path)`, `to_html(path)`, `to_markdown(path)`,
`export(directory, formats)`.

## Building blocks

The analyses are usable on their own:

| Module | Functions |
|---|---|
| `reconsi.inputs` | `load_table`, `as_source`, `register_reader` |
| `reconsi.schema` | `inspect_schema`, `compare_schemas`, `suggest_column_matches` |
| `reconsi.keys` | `analyze_keys`, `profile_keys`, `duplicate_key_table` |
| `reconsi.comparison` | `compare_column`, `ColumnOptions` |
| `reconsi.aggregation` | `aggregate_frame`; `grain.infer_grain`; `diagnosis.aggregation_diagnosis` |
| `reconsi.statistics` | `bias.detect_bias`, `distributions.compare_distributions`, `concentration.concentration`, `intervals.wilson_interval` |
| `reconsi.temporal` | `timeline`, `detect_change_points` |
| `reconsi.rules` | `Rule`, `MetricRule`, `RuleSet`, `overall_status` |
| `reconsi.fingerprints` | `fingerprint_file`, `fingerprint_frame` |
| `reconsi.history` | `HistoryStore` |
| `reconsi.synthetic` | `generate_reconciliation_pair` |
| `reconsi.evaluation` | `run_evaluation`, `SCENARIOS` |

```python
from reconsi.synthetic import generate_reconciliation_pair

pair = generate_reconciliation_pair(rows=10_000, missing_rate=0.02, mismatch_rate=0.01, duplicate_rate=0.005, seed=1)
result = Reconciliation(pair.left, pair.right, keys="order_id", duplicate_strategy="first").run()
print(set(result.missing_right["order_id"]) == pair.truth.missing_from_right)   # True
```
