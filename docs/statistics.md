# Statistics and mismatch diagnosis

Counting mismatches is the start. ReconSI also analyses *how* the datasets differ. Every test
below states its assumptions, reports effect sizes alongside p-values, and is skipped when the
data is too small to support it.

## Difference distributions

For each numeric (and datetime) column, `result.columns[c].differences` summarises the signed
difference *right - left* over all compared pairs; `mismatch_differences` over mismatched pairs
only: count, mean, median, standard deviation, min/max, percentiles (1, 5, 25, 50, 75, 95, 99),
mean absolute difference, and counts of positive, negative and zero differences. The mismatch
rate carries a 95% Wilson confidence interval.

## Systematic differences

`result.analyses["bias"][column]`:

- mean and median signed difference, relative bias,
- an exact two-sided **sign test** on the non-zero differences (robust to outliers and to the
  shape of the distribution), with a Wilcoxon signed-rank p-value as supporting evidence,
- whether the shift looks *proportional* (relative differences tightly clustered) or a *constant
  offset*.

A systematic difference is flagged when at least 10 pairs differ, the sign test p-value is below
`alpha` (default 0.01) and at least 75% of differing pairs move in the same direction. The
message reads like *"Systematic difference detected: the right value is higher by a fairly
consistent 2.50% in 100% of 412 differing pairs"*. It is not called an error: a fee, tax, FX rate
or changed formula can produce exactly this. Assumption: pairs are independent.

```python
import numpy as np
import pandas as pd
from reconsi import reconcile

rng = np.random.default_rng(0)
left = pd.DataFrame({"id": range(500), "region": rng.choice(["East", "West"], 500), "amount": rng.uniform(100, 200, 500).round(2)})
right = left.copy()
west = right["region"] == "West"
right.loc[west, "amount"] = (right.loc[west, "amount"] * 1.025).round(2)

result = reconcile(left, right, keys="id")
print(result.analyses["bias"]["amount"]["message"])
```

## Mismatch concentration

Problem records (value mismatches and missing records) are broken down by every categorical
**dimension**: low-cardinality text, categorical, boolean or code-like integer columns (up to
`max_dimensions`, default 8, each with at most `max_dimension_levels` levels, default 50), or the
columns you list in `dimensions=`. For each dimension: records, problems, problem rate, share of
problems, share of records and *lift* (share of problems / share of records), plus a chi-square
test of independence with Bonferroni correction and Cramér's V.

A dimension is reported as concentrated when the corrected p-value is below `alpha`, the top level
has lift >= 1.5 and at least 5 problem records:

```python
for entry in result.analyses["concentration"]:
    if entry["concentrated"]:
        print(entry["message"])

print(result.drill_down("region"))
```

`drill_down` works recursively: `result.drill_down("product", where={"region": "West"})`, or
several dimensions at once with `result.drill_down("region", "product")`.

## Unmatched population

Are the records missing from one side different from the ones that matched? For each side,
ReconSI compares the distribution of each dimension (and the month of the date column) between
missing and matched records with a chi-square test (Bonferroni corrected, Cramér's V >= 0.1) and
lists over-represented levels: *"Records missing from the right are disproportionately
channel = phone (100% of missing records vs 15% of matched records)"*. This is how extraction
filters and partition problems show up.

## Distribution comparison

Even when rows cannot be matched, the *distributions* of each compared column are compared across
the two datasets (on a seeded sample of up to `distribution_sample` rows per side):

- numeric: mean, median, quantiles, variance, two-sample **Kolmogorov-Smirnov** test,
  **Wasserstein distance** (also normalised by the pooled standard deviation) and standardised
  mean difference;
- categorical: frequency table, **chi-square** test, Cramér's V and **Jensen-Shannon divergence**.

Because large samples make tiny differences "significant", a shift is reported only when
p < `alpha` **and** the effect size is practically relevant (KS >= 0.1 or |SMD| >= 0.2;
JSD >= 0.02 or Cramér's V >= 0.1).

## Temporal analysis

When a date column exists (detected automatically, or set with `date_column=`), records are
bucketed by day, week or month (`time_frequency`: `D`, `W`, `M`) and ReconSI reports, per period,
records, match rate, mismatches and missing records on each side.

- **Change points** use circular binary segmentation on the per-period problem rate with a
  binomial likelihood-ratio statistic and a permutation test (alpha 0.01). Unlike plain binary
  segmentation it also finds temporary regimes (a rate that rises and later falls back).
- **Anomalous periods** are tested against the other periods *of the same regime* (one-sided
  binomial test, Bonferroni corrected, rate at least twice the baseline), so a sustained shift is
  reported once as a change point rather than as many anomalous days.

```python
days = pd.date_range("2026-09-01", periods=20)
left = pd.DataFrame({"id": range(2000), "date": np.repeat(days, 100), "amount": 1.0})
right = left.copy()
incident = (right["date"] >= "2026-09-14") & (right["date"] <= "2026-09-16")
right.loc[incident & (right["id"] % 10 == 0), "amount"] = 2.0

temporal = reconcile(left, right, keys="id").analyses["temporal"]
for cp in temporal["change_points"]:
    print(cp["message"])
```

A change point identifies *when* the rate changed, never *why*.
