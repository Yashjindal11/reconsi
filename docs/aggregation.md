# Aggregation and grain

One of the most common analyst problems: the left dataset is at transaction level, the right is
a daily (or monthly, or per-store) summary. Comparing them row by row is meaningless.

## Reconciling at a coarser grain

```python
import pandas as pd
from reconsi import reconcile

transactions = pd.DataFrame(
    {
        "date": ["2026-10-01"] * 3 + ["2026-10-02"] * 2,
        "revenue": [100.0, 50.0, 25.0, 10.0, 15.0],
    }
)
daily_summary = pd.DataFrame(
    {"date": ["2026-10-01", "2026-10-02"], "revenue": [175.0, 30.0], "orders": [3, 2]}
)

result = reconcile(
    left=transactions,
    right=daily_summary,
    left_group_by=["date"],
    right_keys=["date"],
    aggregations={"revenue": "sum", "orders": "count"},
)
print(result.columns["orders"].mismatches)        # 0: 3 and 2 transactions per day
print(result.value_mismatches[["date", "column", "left_value", "right_value", "difference"]])
```

`left_group_by` / `right_group_by` aggregate that side to the given columns before comparing; the
group-by columns become the keys. Aggregations: `sum`, `count`, `size`, `mean`, `median`, `min`,
`max`, `first`, `last`, `nunique`. `count` on a column that does not exist on the grouped side
(here `orders`) counts rows, which is how a transaction table is reconciled against a summary's
order count. Only aggregated columns are compared.

## Grain inference

For every run ReconSI infers the grain of each dataset: the smallest combination of up to three
non-float columns that is unique (verified on the full data when a sample was used; identifier-like
names such as `*_id` are preferred among equally small candidates).

```python
grain = result.analyses["grain"]
print(grain["left"]["description"], "|", grain["right"]["description"], "|", grain["relationship"])
```

This is labelled an inference: a combination that is unique in this extract is not guaranteed to
be unique by design.

## Aggregation diagnosis

If you reconcile on keys that are duplicated on one side without telling ReconSI how to aggregate,
it checks whether the differences disappear once both sides are summed per key:

```python
naive = reconcile(transactions, daily_summary, keys="date", compare_columns=["revenue"])
print(naive.analyses["aggregation_diagnosis"]["conclusion"])
```

When totals agree after aggregation, the finding is *"Differences are explained by grain"* with a
recommendation to use `left_group_by`; when they do not, ReconSI says so.

## Control totals

Every result also includes control totals: the sum of each numeric column common to both sides,
over all rows, before any matching (`result.analyses["control_totals"]`). They answer "do the
grand totals agree?" independently of key matching.
