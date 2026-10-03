# Schema reconciliation

ReconSI compares column names, types, nullability, column count and order:

```python
import pandas as pd
from reconsi.schema import compare_schemas

left = pd.DataFrame({"id": [1, 2], "legacy_status": ["a", "b"], "revenue": [1, 2], "cust_id": [7, 8]})
right = pd.DataFrame(
    {"id": [1, 2], "revenue": [1.5, 2.0], "customer_id": [7, 8], "discount": [0.0, 0.1], "discount_reason": ["", "promo"]}
)
diff = compare_schemas(left, right)
print(diff.added)          # ['customer_id', 'discount', 'discount_reason']
print(diff.removed)        # ['legacy_status', 'cust_id']
print([(c.column, c.left_dtype, c.right_dtype) for c in diff.dtype_changes])   # revenue int64 -> float64
print([(s.left, s.right) for s in diff.suggestions])                          # [('cust_id', 'customer_id')]
```

The same information is in every reconciliation result (`result.schema`) and on the command line:

```bash
reconsi schema left.parquet right.parquet
```

## Automatic column matching

For columns present on only one side, ReconSI scores candidate pairs using:

- name similarity after normalisation and abbreviation expansion (`cust` -> `customer`,
  `amt` -> `amount`, `txn` -> `transaction`, `dt` -> `date`, `qty` -> `quantity`, ...),
- whether the logical types are compatible,
- similarity of uniqueness (an id column looks like an id column),
- overlap of observed values.

Each column appears in at most one suggestion. Suggestions are **always labelled as suggestions
and never applied**: add the ones you agree with to `column_mapping`.
