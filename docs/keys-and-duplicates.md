# Keys and duplicates

Before any value is compared, ReconSI analyses the keys on both sides, because most "the numbers
don't match" problems start there.

## What is checked

For each side: row count, unique keys, duplicated keys, rows in duplicated keys, maximum and mean
rows per key, the multiplicity distribution, null keys, and per key column: blank values,
leading/trailing whitespace, values that differ only by case, numeric strings with leading zeros,
and values that break the dominant pattern (for example `CUST00123` among `CUST-00123`).

Across sides: the relationship (`one-to-one`, `one-to-many`, `many-to-one`, `many-to-many`),
common / left-only / right-only keys, key columns whose types differ, and **how many rows a naive
join would produce** (which is how duplicated keys silently inflate totals).

```python
import pandas as pd
from reconsi import reconcile

left = pd.DataFrame({"customer_id": ["00123", "00456", "789 "], "revenue": [10.0, 20.0, 30.0]})
right = pd.DataFrame({"customer_id": ["123", "456", "789"], "revenue": [10.0, 20.0, 30.0]})
result = reconcile(left, right, keys="customer_id")

print(result.summary["matched_records"])          # 0: nothing matches as-is
for d in result.keys.normalization_diagnosis:
    print(d["normalization"], d["would_match"])   # strip_leading_zeros 3, trim 1, ...
```

The normalisation diagnosis is reported as a *likely explanation*; it is never applied unless you
ask for it:

```python
fixed = reconcile(left, right, keys="customer_id", key_normalize=["trim", "strip_leading_zeros"])
print(fixed.summary["matched_records"])  # 3
```

Available key normalisations: `trim`, `lowercase`, `casefold`, `collapse_whitespace`,
`unicode_nfc`, `unicode_nfkc`, `strip_leading_zeros`.

When key columns have different types (integer on one side, text on the other) the keys are joined
through a canonical text form (`1`, `1.0` and `"1"` are equal; `"001"` is not) and a note says so.
CSV key columns are read as text so leading zeros survive.

## Duplicate strategies

Duplicated keys never make ReconSI fail outright. Choose how to handle them with
`duplicate_strategy`:

| Strategy | Behaviour |
|---|---|
| `strict` (default) | duplicated keys are set aside as `ambiguous` and listed; everything else is compared |
| `first` / `last` | keep the first / last row per key, in input order |
| `aggregate` | aggregate both sides per key (`aggregations=`, default: sum numeric compare columns) |
| `grouped` | like `aggregate`, and also compare the number of rows per key (`_row_count`) |
| `multiset` | pair rows within a key by sorted value order, so identical rows pair first; leftovers are missing |

```python
left = pd.DataFrame({"customer_id": [123, 123, 123, 123], "revenue": [300.0, 300.0, 350.0, 300.0]})
right = pd.DataFrame({"customer_id": [123] * 5, "revenue": [260.0, 260.0, 270.0, 260.0, 260.0]})

agg = reconcile(left, right, keys="customer_id", duplicate_strategy="aggregate")
row = agg.value_mismatches.iloc[0]
print(row["left_value"], row["right_value"], row["difference"])   # 1250.0 1310.0 60.0

grouped = reconcile(left, right, keys="customer_id", duplicate_strategy="grouped")
print(grouped.columns["_row_count"].mismatches)                     # 1: 4 rows vs 5 rows
```

`result.duplicate_keys` lists every duplicated key with its count on each side, and
`result.ambiguous` holds the rows set aside by the strict strategy.

## The many-to-many trap

```python
orders = pd.DataFrame({"customer_id": [1, 1, 2], "amount": [10.0, 20.0, 5.0]})
payments = pd.DataFrame({"customer_id": [1, 1, 2], "amount": [15.0, 15.0, 5.0]})
result = reconcile(orders, payments, keys="customer_id")
print(result.keys.relationship, result.keys.naive_join_rows)   # many-to-many 5
```

Joining these tables on `customer_id` produces 5 rows for 3 + 3 inputs: any sum over that join
double-counts customer 1. ReconSI reports this as a critical finding and recommends aggregating
each side to the key first (here both totals are 35 per customer 1, so
`duplicate_strategy="aggregate"` reconciles cleanly).
