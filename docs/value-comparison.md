# Value comparison

For every record present on both sides, each compare column is compared according to its type.
By default all columns present on both sides (other than keys) are compared; restrict with
`compare_columns=` or `exclude_columns=`.

## Type resolution

| Left / right types | Compared as |
|---|---|
| both numeric (int/float/decimal) | numeric |
| both datetime / date | datetime |
| both boolean | boolean |
| both text / categorical | string |
| text on one side, numeric / datetime / boolean on the other | the typed side's type: the text is parsed, unparseable values are `datatype` mismatches, and the column is flagged as having different types |
| anything else | canonical text |

Set `columns.<name>.type` (`numeric`, `string`, `datetime`, `boolean`) to force a type, for
example to parse text dates on both sides.

## Numeric tolerance

Values `a` and `b` match when

$$|a - b| \le \max(\text{absolute\_tolerance},\ \text{relative\_tolerance} \cdot \max(|a|, |b|))$$

the same symmetric rule as Python's `math.isclose`. Defaults are exact for integers and a
relative tolerance of `1e-9` for floats, so `0.1 + 0.2` equals `0.3` (differences at
floating-point representation level are reported as zero). Integer columns are compared with
exact integer arithmetic, so values above 2^53 do not lose precision.

```python
import pandas as pd
from reconsi import reconcile

left = pd.DataFrame({"id": [1, 2, 3], "revenue": [100.00, 100.00, 50.0], "quantity": [5, 5, 5]})
right = pd.DataFrame({"id": [1, 2, 3], "revenue": [100.004, 100.02, 50.0], "quantity": [5, 6, 5]})

result = reconcile(
    left,
    right,
    keys="id",
    columns={
        "revenue": {"absolute_tolerance": 0.01, "relative_tolerance": 0.0001},
        "quantity": {"absolute_tolerance": 0},
    },
)
print(result.columns["revenue"].within_tolerance)   # 1: 100.004 matched only within tolerance
print(result.columns["revenue"].mismatches)         # 1: 100.02
print(result.columns["quantity"].mismatches)        # 1
```

The YAML shorthand `tolerances: {revenue: {absolute: 0.01, relative: 0.0001}}` is equivalent.
`decimals: 2` rounds both sides (half-to-even) before comparing; ReconSI never rounds unless you
configure it. Keyword shortcuts `absolute_tolerance=` and `relative_tolerance=` on `reconcile`
apply to every column.

## Strings

Comparison is exact unless you configure normalisation, applied to both sides in order:

| Step | Effect |
|---|---|
| `trim` | strip leading/trailing whitespace |
| `lowercase` / `casefold` | case-insensitive (casefold also handles e.g. German sharp s) |
| `collapse_whitespace` | runs of whitespace become one space |
| `unicode_nfc` / `unicode_nfkc` | Unicode normalisation (composed accents; full-width letters) |
| `strip_leading_zeros` | `00123` -> `123` |

```python
left = pd.DataFrame({"id": [1, 2, 3], "carrier": ["United Airlines"] * 3})
right = pd.DataFrame({"id": [1, 2, 3], "carrier": ["United Airlines", " United Airlines ", "UNITED AIRLINES"]})

exact = reconcile(left, right, keys="id")
print(exact.columns["carrier"].mismatches)                            # 2
print([h["normalization"] for h in exact.columns["carrier"].hints])   # what would explain them

relaxed = reconcile(left, right, keys="id", columns={"carrier": {"normalize": ["trim", "casefold"]}})
print(relaxed.columns["carrier"].mismatches)                          # 0
```

The hints ("2 of 2 string mismatches disappear with trim + casefold") are reported as likely
explanations; they never change the result.

## Datetimes

Timestamps are compared in UTC. Timezone-aware values are converted; naive values are taken as
wall-clock times unless `timezone` is set for the column, in which case they are localised to
that zone (ambiguous or non-existent local times during DST changes become `datatype` mismatches
instead of being guessed). Text is parsed (ISO 8601 first, then mixed formats); offsets such as
`+05:30` or `Z` are honoured.

```python
utc = pd.DataFrame({"id": [1], "booked_at": pd.to_datetime(["2026-10-03 10:00:00"]).tz_localize("UTC")})
ist = pd.DataFrame({"id": [1], "booked_at": pd.to_datetime(["2026-10-03 15:30:00"]).tz_localize("Asia/Kolkata")})
print(reconcile(utc, ist, keys="id").columns["booked_at"].mismatches)   # 0: same instant
```

Options: `tolerance_seconds` (e.g. `1` to ignore sub-second precision differences),
`compare_as_date: true` (compare calendar dates only), `timezone` (for naive values).
When most datetime mismatches share one whole-quarter-hour offset, ReconSI reports it as a likely
timezone problem; when they vanish at second/minute/day precision, as a precision difference.

## Nulls

Null vs null is a match (`null_equals_null: false` to change that). Null vs a value is a `null`
mismatch. Empty string, `0` and null are different values unless `empty_string_as_null: true`.
pandas represents a missing float as `NaN`, so NaN is treated as null. In CSV files an empty
field is read as null, because CSV cannot distinguish the two.

## Column mapping

```python
left = pd.DataFrame({"customer_id": [1, 2], "revenue": [10.0, 20.0]})
right = pd.DataFrame({"cust_id": [1, 2], "sales_amt": [10.0, 21.0]})
result = reconcile(left, right, keys="customer_id", column_mapping={"customer_id": "cust_id", "revenue": "sales_amt"})
print(result.columns["revenue"].mismatches)   # 1
```

`column_mapping` maps **left name -> right name**. Keys can also be mapped with
`right_keys=[...]` (same order as `keys`). Automatic matching only ever *suggests* mappings
([schema](schema.md)).
