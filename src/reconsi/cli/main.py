"""``reconsi`` command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from reconsi._version import __version__
from reconsi.cli.render import frame_text, summary_text
from reconsi.configuration.loader import load_config
from reconsi.configuration.models import ReconConfig
from reconsi.core.errors import ConfigurationError, ReconsiError
from reconsi.core.reconciliation import Reconciliation
from reconsi.core.result import ReconciliationResult
from reconsi.core.serialization import to_jsonable

EXIT_OK, EXIT_FAILED, EXIT_ERROR = 0, 1, 2
DEFAULT_REPORT = "reconsi-report.html"
DEFAULT_HISTORY = ".reconsi/history.db"


# --------------------------------------------------------------------------- helpers
def _csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _pairs(values: Sequence[str] | None, what: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise ConfigurationError(f"{what} must look like left=right, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def contained_path(raw: str, base: Path) -> Path:
    """Resolve an output path from a config file, refusing paths that escape its directory."""
    path = (base / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ConfigurationError(
            f"output path {raw!r} in the configuration escapes {base}; pass it on the command line instead"
        )
    return path


def _write_outputs(result: ReconciliationResult, outputs: dict[str, Any], quiet: bool) -> None:
    written = []
    if outputs.get("html"):
        result.to_html(outputs["html"])
        written.append(outputs["html"])
    if outputs.get("markdown"):
        result.to_markdown(outputs["markdown"])
        written.append(outputs["markdown"])
    if outputs.get("json"):
        result.to_json(outputs["json"])
        written.append(outputs["json"])
    if outputs.get("export_dir"):
        formats = outputs.get("export_formats") or ["csv"]
        files = result.export(outputs["export_dir"], formats=formats)
        written.append(f"{outputs['export_dir']} ({len(files)} files)")
    if not quiet:
        for w in written:
            print(f"wrote {w}")


def _outputs_from_flags(args: argparse.Namespace) -> dict[str, Any]:
    outputs: dict[str, Any] = {
        "html": None,
        "markdown": Path(args.markdown) if args.markdown else None,
        "json": Path(args.json) if args.json else None,
        "export_dir": Path(args.export_dir) if args.export_dir else None,
        "export_formats": _csv(args.export_format) or ["csv"],
    }
    if args.output:
        out = Path(args.output)
        kind = {".md": "markdown", ".json": "json"}.get(out.suffix.lower(), "html")
        outputs[kind] = out
    return outputs


def _exit_code(result: ReconciliationResult, fail_on: str) -> int:
    status = result.status.value
    if fail_on == "never":
        return EXIT_OK
    if status == "FAIL" or (fail_on == "warning" and status == "PASS_WITH_WARNINGS"):
        return EXIT_FAILED
    return EXIT_OK


def _add_output_flags(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("output")
    g.add_argument("-o", "--output", help="report path (.html, .md or .json by suffix)")
    g.add_argument("--json", help="write the JSON result document")
    g.add_argument("--markdown", help="write a Markdown report")
    g.add_argument("--export-dir", help="write evidence tables (missing_left.csv, ...)")
    g.add_argument("--export-format", default="csv", help="csv,parquet,json (default csv)")
    g.add_argument("--no-report", action="store_true", help=f"do not write {DEFAULT_REPORT}")
    g.add_argument(
        "--fail-on",
        choices=["fail", "warning", "never"],
        default="fail",
        help="exit with code 1 on FAIL (default), on warnings too, or never",
    )
    g.add_argument("-q", "--quiet", action="store_true", help="print nothing but errors")
    g.add_argument(
        "--history",
        nargs="?",
        const=DEFAULT_HISTORY,
        help=f"record the run in a local history database (default {DEFAULT_HISTORY})",
    )


# --------------------------------------------------------------------------- commands
def cmd_compare(args: argparse.Namespace) -> int:
    left = args.left_path or args.left
    right = args.right_path or args.right
    if not left or not right:
        raise ConfigurationError("give two datasets: reconsi compare LEFT RIGHT --keys ...")
    options: dict[str, Any] = {}
    if args.config:
        base = load_config(args.config).model_dump(exclude_unset=True, by_alias=True)
        base.pop("left", None)
        base.pop("right", None)
        options.update(base)
    for name, value in (
        ("keys", _csv(args.keys)),
        ("left_keys", _csv(args.left_keys)),
        ("right_keys", _csv(args.right_keys)),
        ("compare_columns", _csv(args.columns)),
        ("exclude_columns", _csv(args.exclude)),
        ("left_group_by", _csv(args.group_by_left)),
        ("right_group_by", _csv(args.group_by_right)),
        ("dimensions", _csv(args.dimensions)),
        ("key_normalize", _csv(args.key_normalize)),
        ("normalize", _csv(args.normalize)),
        ("date_column", args.date_column),
        ("duplicate_strategy", args.strategy),
        ("absolute_tolerance", args.abs_tol),
        ("relative_tolerance", args.rel_tol),
        ("timezone", args.timezone),
        ("backend", args.backend),
        ("name", args.name),
    ):
        if value is not None:
            options[name] = value
    if args.map:
        options["column_mapping"] = {
            **options.get("column_mapping", {}),
            **_pairs(args.map, "--map"),
        }
    if args.agg:
        options["aggregations"] = _pairs(args.agg, "--agg")
    thresholds = dict(options.get("thresholds") or {})
    if args.max_missing is not None:
        thresholds["max_missing_records"] = args.max_missing
    if args.max_mismatch_pct is not None:
        thresholds["max_mismatch_percentage"] = args.max_mismatch_pct
    if thresholds:
        options["thresholds"] = thresholds
    if args.history:
        options["history"] = {"path": args.history}
    if "keys" not in options and "left_keys" not in options and "left_group_by" not in options:
        raise ConfigurationError("--keys is required (e.g. --keys customer_id,date)")
    result = Reconciliation(left, right, **options).run()
    outputs = _outputs_from_flags(args)
    if (
        not any(outputs[k] for k in ("html", "markdown", "json", "export_dir"))
        and not args.no_report
    ):
        outputs["html"] = Path(DEFAULT_REPORT)
    return _finish(result, outputs, args)


def _finish(result: ReconciliationResult, outputs: dict[str, Any], args: argparse.Namespace) -> int:
    if not args.quiet:
        print(summary_text(result.to_dict()))
        print()
    _write_outputs(result, outputs, args.quiet)
    return _exit_code(result, args.fail_on)


def cmd_run(args: argparse.Namespace) -> int:
    path = Path(args.config)
    cfg = load_config(path)
    base = path.resolve().parent
    if args.history and cfg.history is None:
        cfg = ReconConfig.model_validate(
            {**cfg.model_dump(exclude_unset=True, by_alias=True), "history": {"path": args.history}}
        )
    elif cfg.history is not None:
        contained_path(cfg.history.path, base)
    result = Reconciliation(config=cfg, base_dir=base).run()
    outputs = _outputs_from_flags(args)
    if cfg.output is not None:
        for key, raw in (
            ("html", cfg.output.html),
            ("markdown", cfg.output.markdown),
            ("json", cfg.output.json_path),
            ("export_dir", cfg.output.export_dir),
        ):
            if raw and outputs.get(key) is None:
                outputs[key] = contained_path(raw, base)
    if (
        not any(outputs[k] for k in ("html", "markdown", "json", "export_dir"))
        and not args.no_report
    ):
        outputs["html"] = Path(DEFAULT_REPORT)
    return _finish(result, outputs, args)


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.config)
    cfg = load_config(path)
    base = path.resolve().parent
    problems = []
    for side in ("left", "right"):
        spec = getattr(cfg, side)
        if spec is None:
            problems.append(f"{side}: no dataset configured (left.path / right.path)")
            continue
        try:
            from reconsi.inputs.sources import as_source

            as_source(
                spec.path, side, format=spec.format, read_options=spec.read_options, base_dir=base
            )
        except ReconsiError as exc:
            problems.append(f"{side}: {exc}")
    if cfg.output is not None:
        for raw in (
            cfg.output.html,
            cfg.output.markdown,
            cfg.output.json_path,
            cfg.output.export_dir,
        ):
            if raw:
                try:
                    contained_path(raw, base)
                except ConfigurationError as exc:
                    problems.append(str(exc))
    if problems:
        print(f"{path}: invalid")
        for p in problems:
            print(f"  - {p}")
        return EXIT_ERROR
    print(f"{path}: valid")
    print(f"  name: {cfg.name}")
    print(f"  keys: {cfg.resolved_left_keys} (right: {cfg.resolved_right_keys})")
    print(f"  duplicate strategy: {cfg.duplicate_strategy.value}")
    print(f"  rules: {len(cfg.rules)}; column overrides: {len(cfg.columns)}")
    return EXIT_OK


def cmd_schema(args: argparse.Namespace) -> int:
    from reconsi.inputs.sources import load_table
    from reconsi.schema.compare import compare_schemas

    left, right = load_table(args.left), load_table(args.right)
    diff = compare_schemas(left, right, column_mapping=_pairs(args.map, "--map"))
    if args.json:
        print(json.dumps(to_jsonable(diff.to_dict()), indent=2))
        return EXIT_OK
    d = diff.to_dict()
    print(f"left:  {d['left']['column_count']} columns, {d['left']['row_count']:,} rows")
    print(f"right: {d['right']['column_count']} columns, {d['right']['row_count']:,} rows")
    print(f"identical: {d['identical']}; column order changed: {d['order_changed']}")
    for label, key in (("only in right", "added_columns"), ("only in left", "removed_columns")):
        if d[key]:
            print(f"{label}: {', '.join(d[key])}")
    for c in d["dtype_changes"]:
        flag = "" if c["compatible"] else "  (incompatible)"
        print(f"type change: {c['column']}: {c['left_dtype']} -> {c['right_dtype']}{flag}")
    for s in d["suggested_column_matches"]:
        print(f"suggestion (not applied): {s['left']} <-> {s['right']}  score {s['score']}")
    return EXIT_OK


def cmd_inspect(args: argparse.Namespace) -> int:
    from reconsi.aggregation.grain import infer_grain
    from reconsi.inputs.sources import as_source
    from reconsi.keys.analysis import profile_side
    from reconsi.keys.canonical import combined_key
    from reconsi.schema.inspect import inspect_schema

    keys = _csv(args.keys) or []
    frame = as_source(args.path, Path(args.path).name).to_pandas(string_columns=keys)
    schema = inspect_schema(frame, Path(args.path).name)
    grain = infer_grain(frame.head(200_000), total_rows=len(frame), side="dataset")
    out: dict[str, Any] = {"schema": schema.to_dict(), "grain": grain.to_dict()}
    if keys:
        missing = [k for k in keys if k not in frame.columns]
        if missing:
            raise ConfigurationError(
                f"key columns {missing} not found; available: {list(frame.columns)}"
            )
        out["keys"] = profile_side(frame, keys, "dataset", combined_key(frame, keys)).to_dict()
    if args.json:
        print(json.dumps(to_jsonable(out), indent=2))
        return EXIT_OK
    print(f"{schema.name}: {schema.row_count:,} rows, {len(schema.columns)} columns")
    for c in schema.columns:
        print(f"  {c.name:<28}{c.logical_type:<12}{c.dtype:<16}nulls {c.null_count:,}")
    print(f"grain (inferred): {grain.description}")
    if keys:
        k = out["keys"]
        print(
            f"keys {keys}: {k['unique_keys']:,} unique, {k['duplicate_keys']:,} duplicated "
            f"(max {k['max_multiplicity']} rows/key), {k['null_keys']:,} null"
        )
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    from reconsi.history.store import HistoryStore
    from reconsi.reports.html import render_html
    from reconsi.reports.json_report import load_document
    from reconsi.reports.markdown import render_markdown

    doc = (
        HistoryStore(args.history).get(args.source) if args.history else load_document(args.source)
    )
    out = Path(args.output)
    text = render_markdown(doc) if out.suffix.lower() == ".md" else render_html(doc)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return EXIT_OK


def cmd_history(args: argparse.Namespace) -> int:
    from reconsi.history.store import HistoryStore

    path = Path(args.path)
    if not path.exists():
        print(f"no history at {path} (run with --history to record runs)")
        return EXIT_OK
    runs = HistoryStore(path).runs(args.name, args.limit)
    if args.json:
        print(runs.to_json(orient="records", indent=2))
        return EXIT_OK
    cols = [
        "run_id",
        "name",
        "started_at",
        "status",
        "match_percentage",
        "missing_records",
        "value_mismatch_records",
    ]
    print(frame_text(runs[cols] if not runs.empty else runs))
    return EXIT_OK


def _load_doc(ref: str, history: str | None) -> dict[str, Any]:
    from reconsi.history.store import HistoryStore
    from reconsi.reports.json_report import load_document

    if Path(ref).is_file():
        return load_document(ref)
    if history and Path(history).exists():
        return HistoryStore(history).get(ref)
    raise ReconsiError(f"{ref!r} is neither a result JSON file nor a run id in {history}")


def cmd_diff(args: argparse.Namespace) -> int:
    from reconsi.reports.diff import diff_documents, render_diff

    diff = diff_documents(_load_doc(args.before, args.history), _load_doc(args.after, args.history))
    if args.json:
        print(json.dumps(to_jsonable(diff), indent=2))
    else:
        print(render_diff(diff))
    return EXIT_OK


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reconsi",
        description="ReconSI: find out why your numbers don't match.",
    )
    parser.add_argument("--version", action="version", version=f"reconsi {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("compare", help="reconcile two datasets")
    p.add_argument("left", nargs="?", help="left dataset (CSV, Parquet, JSON)")
    p.add_argument("right", nargs="?", help="right dataset")
    p.add_argument("--left", dest="left_path", help=argparse.SUPPRESS)
    p.add_argument("--right", dest="right_path", help=argparse.SUPPRESS)
    p.add_argument("-k", "--keys", help="comma-separated key columns")
    p.add_argument("--left-keys", help="key columns in the left dataset")
    p.add_argument("--right-keys", help="key columns in the right dataset (same order)")
    p.add_argument("-c", "--columns", help="columns to compare (default: all common columns)")
    p.add_argument("--exclude", help="columns not to compare")
    p.add_argument(
        "--map", action="append", metavar="LEFT=RIGHT", help="column mapping (repeatable)"
    )
    p.add_argument(
        "--strategy", choices=["strict", "first", "last", "aggregate", "multiset", "grouped"]
    )
    p.add_argument("--abs-tol", type=float, help="absolute numeric tolerance")
    p.add_argument("--rel-tol", type=float, help="relative numeric tolerance")
    p.add_argument("--normalize", help="string normalisation steps, e.g. trim,casefold")
    p.add_argument("--key-normalize", help="key normalisation steps, e.g. trim,strip_leading_zeros")
    p.add_argument("--timezone", help="timezone for naive timestamps, e.g. America/Chicago")
    p.add_argument("--group-by-left", help="aggregate the left dataset to these columns first")
    p.add_argument("--group-by-right", help="aggregate the right dataset to these columns first")
    p.add_argument("--agg", action="append", metavar="COLUMN=FUNC", help="aggregation (repeatable)")
    p.add_argument("--dimensions", help="dimensions for concentration analysis")
    p.add_argument("--date-column", help="date column for temporal analysis")
    p.add_argument("--max-missing", type=int, help="threshold: max missing records")
    p.add_argument("--max-mismatch-pct", type=float, help="threshold: max mismatch percentage")
    p.add_argument("--backend", choices=["pandas", "duckdb"])
    p.add_argument("--config", help="YAML file with defaults (datasets come from the command line)")
    p.add_argument("--name", help="name of this reconciliation")
    _add_output_flags(p)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("run", help="run a YAML reconciliation job")
    p.add_argument("config")
    _add_output_flags(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("validate", help="validate a YAML job without running it")
    p.add_argument("config")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("schema", help="compare the schemas of two datasets")
    p.add_argument("left")
    p.add_argument("right")
    p.add_argument("--map", action="append", metavar="LEFT=RIGHT")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("inspect", help="profile one dataset: types, nulls, grain, keys")
    p.add_argument("path")
    p.add_argument("-k", "--keys")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("report", help="render a saved result (JSON or run id) as HTML/Markdown")
    p.add_argument("source", help="result JSON file, or run id with --history")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--history", help="history database to look the run id up in")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("history", help="list recorded runs")
    p.add_argument("--path", default=DEFAULT_HISTORY)
    p.add_argument("--name")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("diff", help="compare two runs (result JSON files or run ids)")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--history", default=DEFAULT_HISTORY)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_diff)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code: int = args.func(args)
        return code
    except ReconsiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
