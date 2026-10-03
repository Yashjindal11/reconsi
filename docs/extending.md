# Extending ReconSI

## New input formats

```python
from pathlib import Path

import pandas as pd
from reconsi.inputs import load_table, register_reader


def read_pipe_delimited(path: Path, options: dict) -> pd.DataFrame:
    return pd.read_csv(path, sep="|", **options)


register_reader("psv", read_pipe_delimited, allowed_options={"encoding"})
```

Pass `format="psv"` (or `left: {path: ..., format: psv}`). Only the listed options can be passed
from configuration files. Objects with a `to_pandas()` method (Arrow tables, Polars frames) are
accepted directly.

ReconSI deliberately does not execute SQL from configuration files. To reconcile query results,
run the queries in your own code and pass DataFrames (or DuckDB relations via `.df()`).

## New backends

Subclass `reconsi.backends.base.TableBackend` and implement loading, row counts, sampling, sums,
aggregation, de-duplication, key removal, occurrence numbering, key casting / normalisation and
a chunked full outer join. The join must yield pandas chunks with the key columns, `_side`
(`both` / `left_only` / `right_only`) and `l.`/`r.`-prefixed value columns; value comparison is
shared, so every backend gets identical semantics. `tests/backends/test_backend_parity.py` shows
how to check a backend against the pandas reference.

## Custom rules

```python
from dataclasses import dataclass

from reconsi.rules import Outcome, Rule, RuleContext, RuleResult


@dataclass
class NoMissingOnWeekdays(Rule):
    name: str = "weekday_coverage"
    severity: str = "error"

    def evaluate(self, context: RuleContext) -> RuleResult:
        missing = context.summary["missing_records"]
        outcome = Outcome.PASS if missing == 0 else Outcome.FAIL
        return RuleResult(self.name, "custom", outcome, self.severity, "custom", float(missing))
```

Evaluate with `RuleSet([NoMissingOnWeekdays()]).evaluate(context)`; built-in configuration rules
are created by `RuleSet.from_config(config, compare_columns)`.

## Custom string normalisations

`reconsi.comparison.values.STRING_NORMALIZERS` maps a name to a function on a pandas string
Series; configuration validation only accepts the built-in names, so register new ones in code
you control and call `compare_column` directly.
