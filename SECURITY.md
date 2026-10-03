# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue. Report privately through
[GitHub security advisories](https://github.com/Yashjindal11/reconsi/security/advisories/new).
Include the affected version (`reconsi --version`), a description and a minimal reproduction
using synthetic data, never your real data. You can expect an acknowledgement within a week.
Fixes are released as patch versions and credited in the changelog unless you prefer otherwise.

Supported versions: the latest minor release.

## Threat model

ReconSI reads data that may be sensitive, and configuration files that may come from someone
else. It is designed so that neither can make it execute code or reach the network:

- **YAML** is parsed with `yaml.safe_load` and validated against a strict schema (unknown keys
  are errors; files over 1 MB are rejected).
- **No code or SQL from configuration.** Rules use a fixed set of metrics. The DuckDB backend
  builds SQL only from quoted identifiers and integer literals; file paths and values are passed
  as parameters or through DuckDB's relation API.
- **Reader options** from configuration are limited to an allow-list per format, so options such
  as `storage_options` cannot be used to reach remote storage.
- **Only local paths.** URLs are rejected. Paths in a YAML job resolve relative to the job file.
- **Output paths** from a YAML job must stay inside the job's directory (path traversal is
  rejected); command-line flags are trusted. Export file names are fixed and never derived from
  data values.
- **HTML reports** escape every data value; they load no external resources.
- **No pickle.** Results are serialised as JSON; run history is SQLite with parameterised queries.
- **Subprocesses**: only `git rev-parse` / `git status` with fixed arguments and no shell, to
  record the commit.

## What ReconSI does not protect against

- Reports and evidence exports contain samples of your data. Store and share them like the data.
- Very large or adversarial inputs can exhaust memory; set `max_detail_rows`, compare fewer
  columns, or use the DuckDB backend with `backend_options.memory_limit`.
