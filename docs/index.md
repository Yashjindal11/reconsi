# ReconSI documentation

**Reconciliation Intelligence: find out why your numbers don't match.**

Two systems, reports, queries or extracts are supposed to describe the same business reality,
and they do not agree. ReconSI compares them and tells you, with evidence:

- what matches, what does not, and how much does not;
- whether records are missing or extra, and whether the missing ones share a profile;
- whether keys are duplicated, malformed, differently typed or differently formatted;
- which columns differ, by how much, in which direction, and whether the direction is systematic;
- whether the difference is a grain (aggregation) problem rather than a value problem;
- where mismatches concentrate (region, product, channel ...) and when they started.

It runs locally, uses no language models or API keys, and is deterministic: the same inputs and
configuration give the same answer. Every finding is labelled as **observed**, **statistically
supported**, a **likely explanation** or the outcome of a **user-configured rule**, so a guess is
never presented as a fact.

## Contents

| Page | What it covers |
|---|---|
| [Quickstart](quickstart.md) | Install, first reconciliation in Python and on the command line |
| [Core concepts](concepts.md) | Records, statuses, evidence labels, the result object |
| [Keys and duplicates](keys-and-duplicates.md) | Key analysis, duplicate strategies, key normalisation |
| [Value comparison](value-comparison.md) | Numeric tolerance, strings, datetimes, nulls, column mapping |
| [Schema reconciliation](schema.md) | Added, removed, renamed and retyped columns; match suggestions |
| [Aggregation and grain](aggregation.md) | Reconciling transactions against summaries; grain inference |
| [Statistics and diagnosis](statistics.md) | Bias, distributions, concentration, unmatched population, time |
| [Rules and status](rules.md) | Thresholds, named rules, PASS / PASS_WITH_WARNINGS / FAIL |
| [Reports](reports.md) | HTML, Markdown, JSON and evidence exports |
| [JSON result schema](json-schema.md) | The stable machine-readable document |
| [Configuration reference](configuration.md) | Every YAML / keyword option |
| [CLI](cli.md) | `reconsi compare`, `run`, `validate`, `schema`, `inspect`, `report`, `history`, `diff` |
| [Python API](python-api.md) | `reconcile`, `Reconciliation`, result methods |
| [Large datasets and DuckDB](large-datasets.md) | Backends, memory, performance |
| [Extending ReconSI](extending.md) | New readers, backends and rules |
| [Examples](examples.md) | Seven complete, runnable scenarios |
| [Evaluation](evaluation.md) | Detection accuracy against known ground truth |
| [Research notes](research.md) | Simulation studies and scaling measurements |
| [FAQ](faq.md) | Common questions |
