# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-03

First public release.

### Added
- `reconcile()` and `Reconciliation` APIs returning a serialisable `ReconciliationResult`.
- Inputs: pandas DataFrames, CSV/TSV, Parquet, JSON/JSONL, objects with `to_pandas()`;
  reader extension point; key columns read as text from text formats.
- Key analysis: uniqueness, multiplicity distribution, nulls, blanks, whitespace, case variants,
  leading zeros, malformed patterns, type differences, relationship classification,
  naive-join inflation and a normalisation diagnosis for unmatched keys.
- Duplicate strategies: `strict`, `first`, `last`, `aggregate`, `grouped`, `multiset`.
- Value comparison: symmetric numeric tolerance (absolute, relative, decimals), exact integer
  comparison, string normalisation, timezone-aware datetime comparison with tolerance and
  date-only mode, boolean comparison, explicit null semantics, text-vs-typed parsing, column
  mapping, per-column options and diagnostic hints.
- Schema comparison with column-match suggestions (never applied).
- Grain reconciliation (`left_group_by` / `right_group_by`), grain inference, aggregation
  diagnosis and control totals.
- Statistics: difference distributions, Wilson intervals, sign-test systematic-bias detection,
  KS / Wasserstein / chi-square / Jensen-Shannon distribution comparison, mismatch concentration
  with drill-down, unmatched-population analysis, largest differences.
- Temporal analysis: per-period match rates, circular binary segmentation change points and
  regime-relative anomalous periods.
- Rules engine with thresholds, column limits, critical columns, named rules and explicit
  PASS / PASS_WITH_WARNINGS / FAIL semantics.
- Evidence-labelled findings and recommendations.
- Reports: standalone offline HTML, Markdown, versioned JSON document, CSV/Parquet/JSON evidence
  exports, optional matplotlib plots.
- CLI: `compare`, `run`, `validate`, `schema`, `inspect`, `report`, `history`, `diff`.
- YAML jobs with safe loading and strict validation.
- Reproducibility metadata, dataset fingerprints, SQLite run history and run diff.
- DuckDB backend with parity tests against the pandas backend.
- Synthetic reconciliation generator with ground truth, evaluation framework, research
  experiments and scale benchmark.
