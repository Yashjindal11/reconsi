# Rules and status

## The overall status

| Status | Definition |
|---|---|
| `FAIL` | at least one rule with severity `error` broke its threshold |
| `PASS_WITH_WARNINGS` | no rule failed, but a `warning` rule broke its threshold, **or** differences exist that are within a configured non-zero threshold |
| `PASS` | every applicable rule passed and there was nothing to report |

The status never hides detail: every rule result is listed in the report and in
`result.rule_results`.

## Default rules

With no configuration, ReconSI is strict:

| Rule | Metric | Limit | Severity |
|---|---|---|---|
| `no_missing_records` | missing records (both sides) | 0 | error |
| `no_ambiguous_records` | rows set aside by the `strict` duplicate strategy (never compared) | 0 | error |
| `<column>_matches` (one per compared column) | mismatches in that column | 0 | error |
| `no_duplicate_keys` | duplicated keys (both sides) | 0 | warning |
| `no_schema_changes` | added + removed + retyped columns | 0 | warning |

## Thresholds

Thresholds replace the matching defaults. Percentages are on a 0-100 scale.

```yaml
thresholds:
  max_missing_records: 10          # replaces no_missing_records
  max_missing_percentage: 0.5
  max_mismatched_records: 100      # replaces all <column>_matches rules
  max_mismatch_percentage: 0.1
  max_duplicate_keys: 0            # now an error, not a warning
  max_schema_changes: 2
```

Column-specific limits:

```yaml
columns:
  revenue:
    max_mismatch_percentage: 0.5
  order_status:
    max_mismatches: 10
  customer_id_hash:
    critical: true                 # any mismatch fails the reconciliation
```

## Named rules

Rules are reusable, named and can carry comparison settings:

```yaml
rules:
  - name: revenue_match
    column: revenue
    type: numeric
    absolute_tolerance: 0.01           # how revenue is compared
                                       # (no metric: no revenue mismatches allowed)
  - name: customer_match
    column: customer_name
    type: string
    normalize: [trim, lowercase]
    max: 5                             # at most 5 mismatches
  - name: coverage
    metric: match_percentage
    min: 99.5
    severity: warning
  - name: revenue_total
    metric: column_total_difference
    column: revenue
    max: 100
```

Metrics: `missing_records`, `missing_left_records`, `missing_right_records`,
`missing_percentage`, `mismatched_records`, `mismatch_percentage`, `match_percentage`,
`duplicate_keys`, `ambiguous_records`, `schema_changes`, and per column `column_mismatches`,
`column_mismatch_percentage`, `column_total_difference` (absolute difference of column sums over
matched records), `column_total_relative_difference` (in percent).

Each rule produces `pass`, `warning`, `fail` or `not_applicable` (for example a total-difference
rule on a text column).

## In Python

```python
import pandas as pd
from reconsi import reconcile

left = pd.DataFrame({"id": range(100), "revenue": [100.0] * 100})
right = left.copy()
right.loc[:1, "revenue"] = 101.0

result = reconcile(left, right, keys="id", thresholds={"max_mismatch_percentage": 5})
print(result.status)   # PASS_WITH_WARNINGS: 2% mismatches, within the 5% threshold
for rule in result.rule_results:
    print(rule.name, rule.outcome.value, rule.message)
```

Custom rule classes can be added in Python by subclassing `reconsi.rules.Rule`
(see [extending](extending.md)).
