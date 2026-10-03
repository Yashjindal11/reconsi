# FAQ

**Does ReconSI use AI, embeddings or any external service?**
No. Everything is deterministic comparison, statistics and heuristics, computed locally. No
network access, no API keys.

**Which side is "left"?**
Whichever you consider the reference. Names in the configuration and reports are left-hand names;
`missing_right` means "present in left, missing from right".

**Why is my status FAIL when only 0.01% of records differ?**
The defaults allow no differences. Set `thresholds` (for example `max_mismatch_percentage: 0.1`) to
tolerate them; the status becomes PASS_WITH_WARNINGS and the differences are still reported.

**Why do `001` and `1` not match?**
They are different strings. ReconSI reports how many unmatched keys would match after
`strip_leading_zeros`, but only applies it if you set `key_normalize`.

**Does ReconSI round numbers?**
Only if you set `decimals`. Float columns get a relative tolerance of 1e-9 so that pure
floating-point representation differences (0.1 + 0.2 vs 0.3) are not reported.

**My CSV has dates as text and my Parquet file has timestamps.**
The text side is parsed as dates; values that cannot be parsed are reported as `datatype`
mismatches and the column is flagged as having different types.

**Why are some duplicate keys "ambiguous"?**
With the default `strict` strategy ReconSI will not guess which of several rows with the same key
corresponds to which. Choose `first`, `last`, `aggregate`, `grouped` or `multiset`.

**Are the statistical tests reliable on huge datasets?**
p-values become tiny for practically irrelevant differences, so ReconSI requires both a small
p-value and a practical effect size before flagging a shift, concentration or systematic difference.
Tests assume independent records; time-series autocorrelation is not modelled.

**Can it reconcile tables larger than memory?**
The DuckDB backend loads, de-duplicates, aggregates and joins out of core, but joined rows are
still compared in Python chunks and record-level results are kept in memory. See
[large datasets](large-datasets.md) for measured limits.

**Is anything sent anywhere?**
No. Reports can contain sample rows of your data; treat them like the data itself.

**How do I reproduce a run?**
The result records the ReconSI and Python versions, package versions, the full configuration and
its hash, input fingerprints, the seed and the Git commit of the working directory.
