# Large datasets and the DuckDB backend

## Backends

| Backend | Install | How it works |
|---|---|---|
| `pandas` (default) | built in | loads both datasets into memory, joins with `merge` |
| `duckdb` | `pip install "reconsi[duckdb]"` | DuckDB scans CSV / Parquet / JSON directly and performs loading, de-duplication, aggregation and the full outer join; joined rows are streamed back in Arrow batches |

```py
result = reconcile("a.parquet", "b.parquet", keys="id", backend="duckdb",
                   backend_options={"memory_limit": "4GB", "threads": 4})
```

Both backends feed the same comparison code, so results are identical (verified by
`tests/backends/test_backend_parity.py`). Identifiers in generated SQL are quoted; no
user-supplied SQL is ever executed.

## Measured performance

`python benchmarks/bench_scale.py --sizes 10000,100000,1000000,10000000` on an Apple M4
MacBook Air (16 GB RAM), Python 3.12, pandas 3.0, DuckDB 1.5. Two Parquet files with 2% missing,
1% extra and 0.5% mismatched rows, 11 columns, all compared. Wall time of `reconcile()`, peak
resident memory of a fresh process, single runs. Raw data: `benchmarks/results/scale.json`.

| Rows per side | pandas | DuckDB |
|---|---|---|
| 10,000 | 0.45 s, 206 MB | 0.64 s, 236 MB |
| 100,000 | 1.2 s, 362 MB | 1.7 s, 428 MB |
| 1,000,000 | 6.2 s, 1.6 GB | 8.4 s, 2.3 GB |
| 10,000,000 | 88 s, 4.7 GB | 76 s, 6.0 GB |

Honest reading: at these sizes the two backends are close. Value comparison, key analysis and
the statistical analyses run in Python on the joined rows for both, and dominate the run time.
DuckDB pulls ahead slightly at 10M rows on time but uses more memory, because its own buffers
coexist with the record-level results held in pandas. ReconSI does not yet push comparisons into
SQL.

## What stays in memory

Regardless of backend, ReconSI keeps per record: the key columns, the status, the analysis
dimensions and the date (for concentration, drill-down and the timeline), plus the signed
differences of numeric columns (for exact statistics). Detailed evidence rows (value mismatches,
missing records) are capped at `max_detail_rows` (default 1,000,000); counts and statistics always
use all rows.

## Practical advice

- Compare only what you need: `compare_columns=[...]` reduces both work and memory.
- Prefer Parquet over CSV: typed columns, faster scans, and fingerprints read only metadata.
- Limit analysis dimensions on very wide tables (`dimensions=[...]` or `max_dimensions=`).
- Distribution tests use a seeded sample (`distribution_sample`, default 200,000 rows per side).
- Fingerprints hash files in 1 MB chunks (constant memory); files over 512 MB are fingerprinted
  from size, first and last megabyte and Parquet metadata.
