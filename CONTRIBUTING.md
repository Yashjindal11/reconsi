# Contributing to ReconSI

Thanks for helping people find out why their numbers don't match.

## Ground rules

- **Never overstate.** Every finding carries an evidence label: `observed`,
  `statistically_supported`, `likely_explanation` or `user_configured_rule`. A heuristic is a
  likely explanation, never a fact; ReconSI does not claim causes.
- **Never change data silently.** Normalisation, rounding, type coercion and key casting happen
  only when configured, or are reported in the result's notes.
- **No invented numbers.** Benchmark, evaluation and research figures come from the scripts in
  `benchmarks/` and are committed with their raw results. Never edit them by hand.
- **No LLMs, no network.** Contributions must not add model APIs, telemetry or outbound calls.
- **Same semantics on every backend.** Value comparison is shared; backends only move data.

## Development setup

```bash
git clone https://github.com/Yashjindal11/reconsi && cd reconsi
python3.12 -m venv .venv                     # 3.11+
.venv/bin/pip install -e ".[dev]"
scripts/check.sh                             # format check, lint, mypy --strict, tests
.venv/bin/python scripts/run_examples.py
.venv/bin/python scripts/preview_report.py   # writes reports/preview.html (git-ignored)
```

Python code blocks in `README.md` and `docs/*.md` are executed by `tests/docs/test_docs.py`
(use ```` ```py ```` for blocks that should not run).

## Where things live

| Package | Responsibility |
|---|---|
| `inputs` | reading DataFrames and files into `TableSource`s |
| `backends` | pandas / DuckDB: load, aggregate, de-duplicate, join |
| `keys`, `schema` | key and schema analysis |
| `comparison` | per-column value comparison and record accumulation |
| `aggregation`, `statistics`, `temporal` | analyses |
| `rules`, `findings` | judgement: status, findings, recommendations |
| `reports`, `visualization`, `cli` | output |
| `synthetic`, `evaluation` | ground-truth testing |

## Tests

- New comparison behaviour: unit tests in `tests/unit/`, including the "must stay quiet" case.
- New backend behaviour: extend `tests/backends/test_backend_parity.py`.
- New diagnosis: add a scenario to `reconsi.evaluation.SCENARIOS` (and the generator if needed),
  then rerun `python benchmarks/evaluate.py`.
- Statistical changes: document assumptions and limitations in `docs/statistics.md` and rerun
  `python benchmarks/experiments.py`.

## Commits and pull requests

- Conventional Commits (`feat: ...`, `fix(keys): ...`, `perf: ...`, `docs: ...`).
- One logical change per commit; keep every commit working.
- Update `CHANGELOG.md` under *Unreleased* when behaviour changes.

## Releases

1. Move *Unreleased* entries in `CHANGELOG.md` under a new version heading.
2. Bump `src/reconsi/_version.py`.
3. Commit `chore: release vX.Y.Z`, tag `vX.Y.Z` and push the tag. The release workflow tests,
   builds and publishes a GitHub release with the changelog section as notes.
