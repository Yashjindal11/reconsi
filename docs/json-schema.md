# JSON result schema (version 1.0)

`result.to_dict()` / `result.to_json()` / `reconsi compare --json` produce one JSON object. The
schema is versioned by `schema_version`; fields are only added within a major version.
`reconsi.reports.json_report.validate_document(doc)` checks a document and
`load_document(path)` loads and validates one.

```json
{
  "schema_version": "1.0",
  "name": "daily_sales_reconciliation",
  "status": "FAIL",
  "metadata": {},
  "summary": {},
  "schema": {},
  "keys": {},
  "records": {},
  "columns": {},
  "analyses": {},
  "rules": [],
  "findings": [],
  "recommendations": [],
  "notes": [],
  "configuration": {}
}
```

All numbers are finite or `null`; timestamps are ISO-8601 strings; percentages are 0-100.

## `status`
`"PASS"`, `"PASS_WITH_WARNINGS"` or `"FAIL"` ([rules](rules.md)).

## `metadata`
`run_id`, `reconsi_version`, `python_version`, `platform`, `packages` (versions of numpy,
pandas, scipy, pydantic, pyarrow, duckdb), `started_at`, `duration_seconds`, `backend`, `left` /
`right` (`name`, `kind`, `path`, `format`), `left_fingerprint` / `right_fingerprint` (`digest`
plus method-specific fields), `config_hash`, `seed`, `date_column`, `dimensions`, `git_commit`,
`git_dirty`.

## `summary`
| Field | Type | Meaning |
|---|---|---|
| `left_rows`, `right_rows` | int | input rows |
| `left_records`, `right_records` | int | rows after grain / duplicate handling |
| `keys` | [str] | join keys (may include `_occurrence` for the multiset strategy) |
| `duplicate_strategy` | str | strategy used |
| `total_records` | int | matched + value_mismatch + missing_left + missing_right |
| `compared_records` | int | matched + value_mismatch |
| `matched_records`, `value_mismatch_records` | int | |
| `missing_left` | int | records only in the right dataset |
| `missing_right` | int | records only in the left dataset |
| `missing_records` | int | sum of both |
| `ambiguous_records` | int | rows set aside by the strict strategy |
| `duplicate_keys_left`, `duplicate_keys_right` | int | duplicated keys per side |
| `match_percentage`, `mismatch_percentage`, `missing_percentage` | float | see [concepts](concepts.md) |
| `columns_compared`, `columns_with_mismatches`, `value_mismatches` | int | `value_mismatches` counts cells |

## `schema`
`left`, `right` (`name`, `row_count`, `column_count`, `columns[]` with `name`, `dtype`,
`logical_type`, `position`, `null_count`, `nullable`), `identical`, `common_columns`,
`added_columns` (right only), `removed_columns` (left only), `renamed_columns`
(configured left -> right), `dtype_changes[]`, `nullability_changes[]`, `order_changed`,
`suggested_column_matches[]` (`left`, `right`, `score`, `signals`, `label: "suggestion"`).

## `keys`
`keys`, `relationship`, `common_keys`, `left_only_keys`, `right_only_keys`, `naive_join_rows`,
`join_inflation`, `dtype_mismatches[]`, `normalization_diagnosis[]` (`normalization`,
`would_match`, `share_of_left_only`, `examples`, `sampled`), and `left` / `right` profiles:
`rows`, `unique_keys`, `is_unique`, `duplicate_keys`, `rows_in_duplicate_keys`,
`max_multiplicity`, `mean_records_per_key`, `multiplicity_distribution` (`"1"`, `"2"`, `"3"`,
`"4-5"`, `"6-10"`, `"11+"`), `null_keys`, `dtypes`, `format_issues` (per column: `blank`,
`whitespace`, `case_variants`, `leading_zeros`, `malformed`, `dominant_pattern`,
`malformed_examples`), `duplicate_examples[]`.

## `records`
Samples (up to `sample_size` rows each, default 20): `missing_left_sample`,
`missing_right_sample`, `value_mismatch_sample` (key columns, `column`, `left_value`,
`right_value`, `difference`, `relative_difference`, `mismatch_type`), `ambiguous_sample`,
`duplicate_keys_sample`. Full tables come from `result.export()`.

## `columns`
Keyed by column name: `kind`, `classification`, `left_dtype`, `right_dtype`,
`datatype_mismatch`, `critical`, `compared`, `matches`, `mismatches`, `match_percentage`,
`mismatch_percentage`, `mismatch_percentage_ci95` ([low, high]), `within_tolerance`,
`both_null`, `null_mismatches`, `mismatch_types` ({type: count}), `comparison` (effective
settings), `differences` / `mismatch_differences` / `relative_differences` (`count`, `mean`,
`median`, `std`, `min`, `max`, `mean_absolute`, `sum`, `positive`, `negative`, `zero`, `p01` ...
`p99`), `totals` (`left_sum`, `right_sum`, `difference`, `relative_difference`),
`mismatch_histogram` (`counts`, `edges`), `hints[]`.

## `analyses`
| Key | Content |
|---|---|
| `control_totals` | `rows` and per-column sums before matching |
| `grain` | `left`, `right` inferences, `relationship`, `keys_are_grain` (label `inference`) |
| `aggregation_diagnosis` | present when keys are duplicated: per-column totals after aggregation, `explained_by_grain`, `conclusion` |
| `bias` | per numeric column: sign test, Wilcoxon, direction, consistency, `systematic`, `message` |
| `distributions` | `sampled`, `sample_size`, `columns` (KS / Wasserstein or chi-square / JSD, `shift`) |
| `concentration` | per dimension: `levels[]`, chi-square, Bonferroni p, Cramér's V, `top_level`, `concentrated`, `message` |
| `unmatched_population` | `missing_from_right` / `missing_from_left`: dimensions with over-represented levels |
| `largest_differences` | per numeric column: `absolute`, `relative`, `positive`, `negative` top rows |
| `temporal` | `periods[]`, `anomalous_periods[]`, `change_points[]`, `overall_problem_rate`, `trend_slope_per_period` |

## `rules`
`name`, `metric`, `column`, `outcome` (`pass` / `warning` / `fail` / `not_applicable`),
`severity`, `source` (`default` / `threshold` / `column` / `rule`), `observed`, `max`, `min`,
`message`, `description`.

## `findings`
`id`, `category`, `severity` (`critical` / `warning` / `info`), `evidence` (`observed` /
`statistically_supported` / `likely_explanation` / `user_configured_rule`), `title`, `detail`,
`recommendation`, `data`. Ordered by severity.

## `configuration`
The full validated configuration, so a run can be reproduced.
