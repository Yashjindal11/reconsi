# Command-line interface

```text
reconsi compare LEFT RIGHT --keys K[,K...] [options]   reconcile two files
reconsi run JOB.yaml                                    run a YAML job
reconsi validate JOB.yaml                               validate a job without running it
reconsi schema LEFT RIGHT                               compare schemas only
reconsi inspect FILE [--keys K]                         profile one dataset (types, nulls, grain, keys)
reconsi report RESULT.json -o report.html               re-render a saved result (or a run id with --history)
reconsi history [--path DB] [--name NAME]               list recorded runs
reconsi diff BEFORE AFTER                               compare two runs (JSON files or run ids)
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | completed; status PASS or PASS_WITH_WARNINGS (or any status with `--fail-on never`) |
| 1 | completed; status FAIL (or PASS_WITH_WARNINGS with `--fail-on warning`) |
| 2 | configuration or input error (message on stderr) |

## `reconsi compare`

```bash
reconsi compare sales_a.parquet sales_b.parquet \
  --keys customer_id,date \
  --output report.html
```

`--left FILE --right FILE` may be used instead of positional arguments.

| Option | Meaning |
|---|---|
| `-k, --keys` | key columns (comma-separated) |
| `--left-keys`, `--right-keys` | per-side key names |
| `-c, --columns`, `--exclude` | columns to compare / skip |
| `--map LEFT=RIGHT` | column mapping (repeatable) |
| `--strategy` | duplicate strategy |
| `--abs-tol`, `--rel-tol` | numeric tolerances for all columns |
| `--normalize trim,casefold` | string normalisation for all columns |
| `--key-normalize` | key normalisation |
| `--timezone` | timezone for naive timestamps |
| `--group-by-left`, `--group-by-right`, `--agg COL=FUNC` | grain reconciliation |
| `--dimensions`, `--date-column` | analysis columns |
| `--max-missing N`, `--max-mismatch-pct P` | thresholds |
| `--backend pandas|duckdb` | compute backend |
| `--config job.yaml` | take every other option from a YAML file |
| `-o, --output` | report path; `.html`, `.md` or `.json` by suffix |
| `--json`, `--markdown` | additional outputs |
| `--export-dir DIR`, `--export-format csv,parquet,json` | evidence tables |
| `--no-report` | do not write the default `reconsi-report.html` |
| `--history [DB]` | record the run (default `.reconsi/history.db`) |
| `--fail-on fail|warning|never` | exit-code policy |
| `-q, --quiet` | print nothing but errors |

With no output options, `compare` and `run` write `reconsi-report.html` in the current directory.

Grain example (transactions vs a daily summary):

```bash
reconsi compare transactions.csv daily.csv \
  --group-by-left date --right-keys date \
  --agg revenue=sum --agg orders=count --abs-tol 0.01
```

## `reconsi run` and `validate`

Paths inside the YAML file are resolved relative to the file. Output paths from the YAML file
must stay inside its directory (pass an explicit `--output` to write elsewhere). `validate`
checks the schema of the file, that input files exist and that output paths are allowed.

## `reconsi history` and `diff`

```bash
reconsi run job.yaml --history          # or `history: {path: ...}` in the job
reconsi history --name daily_sales
reconsi diff 20261002T060000Z-1a2b3c 20261003T060000Z-4d5e6f
```

`diff` reports status changes, metric deltas, per-column mismatch changes, whether the input
fingerprints or the configuration changed, and new / resolved findings.

## CI usage

```bash
reconsi run checks/orders.yaml --fail-on warning --json out/orders.json --quiet
```
