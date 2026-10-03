# Core concepts

## Left, right, keys

ReconSI compares a **left** and a **right** dataset. **Keys** are the columns that identify the same
business record on both sides (`customer_id`, or `date + store_id + product_id`). Column names are
always the *left* names; `column_mapping` and `right_keys` translate right-hand names.

## Record statuses

Every distinct key ends up in exactly one status:

| Status | Meaning |
|---|---|
| `matched` | present on both sides, every compared column matches |
| `value_mismatch` | present on both sides, at least one compared column differs |
| `missing_right` | present only in the **left** dataset (missing from the right) |
| `missing_left` | present only in the **right** dataset (missing from the left) |
| `ambiguous` | the key is duplicated and the `strict` strategy refused to guess a pairing |

Rows whose key contains a null never match anything (SQL semantics) and are reported as missing.

Summary percentages are defined as:

- `match_percentage` = matched / (matched + value_mismatch + missing_left + missing_right)
- `mismatch_percentage` = value_mismatch / (matched + value_mismatch)
- `missing_percentage` = (missing_left + missing_right) / all records

## Cell-level mismatch types

A differing value is classified as `numeric`, `string`, `datetime`, `boolean`, `null` (one side
null, the other not) or `datatype` (a value could not be interpreted as the column's type, for
example `"abc"` in a numeric column). Each compared column also gets a classification:
`exact_match`, `match_within_tolerance`, or `<dominant type>_mismatch`.

## Evidence labels

Findings never overstate what is known:

| Label | Meaning | Example |
|---|---|---|
| `observed` | a direct count or measurement | "1,204 records are missing from the right" |
| `statistically_supported` | passed a stated statistical test | "revenue is systematically 2.5% higher on the right (sign test p < 0.001)" |
| `likely_explanation` | a heuristic diagnosis that fits the evidence | "timestamps differ by a constant +05:30, consistent with a timezone difference" |
| `user_configured_rule` | the outcome of a configured rule or threshold | "max_mismatch_percentage = 0.4% breaks max 0.1%" |

ReconSI does not claim causes. A change point says *when* the mismatch rate changed, not *why*.

## The result object

`reconcile(...)` returns a `ReconciliationResult`:

| Attribute | Content |
|---|---|
| `status` | `Status.PASS`, `PASS_WITH_WARNINGS` or `FAIL` ([rules](rules.md)) |
| `summary` | record counts and percentages |
| `schema` | schema differences ([schema](schema.md)) |
| `keys` | key analysis ([keys](keys-and-duplicates.md)) |
| `columns` | per-column statistics |
| `matched`, `mismatched` | keys by status |
| `missing_left`, `missing_right`, `value_mismatches`, `ambiguous`, `duplicate_keys` | evidence tables |
| `analyses` | grain, control totals, bias, distributions, concentration, unmatched population, temporal |
| `rule_results`, `findings`, `recommendations` | judgement and next steps |
| `metadata` | version, timings, fingerprints, configuration hash, git commit, seed |

Methods: `drill_down()`, `largest_differences()`, `record_mismatches()`, `to_dict()`, `to_json()`,
`to_html()`, `to_markdown()`, `export()`.
