"""The reconciliation engine: ``Reconciliation(...).run()`` and the ``reconcile(...)`` shortcut."""

from __future__ import annotations

import platform
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from reconsi._version import __version__
from reconsi.aggregation.aggregate import default_aggregations
from reconsi.backends import make_backend
from reconsi.backends.base import OCCURRENCE, ROW_COUNT, SIDES, Side, TableBackend
from reconsi.comparison.records import STATUS, RecordAccumulator
from reconsi.comparison.values import resolve_kind
from reconsi.configuration.loader import config_from_dict
from reconsi.configuration.models import ReconConfig, SourceConfig
from reconsi.core.dtypes import logical_type
from reconsi.core.errors import ConfigurationError
from reconsi.core.profiling import detect_date_column, detect_dimensions
from reconsi.core.result import ReconciliationResult
from reconsi.core.types import DuplicateStrategy, RecordStatus, Status
from reconsi.inputs.sources import TableSource, as_source
from reconsi.keys.analysis import analyze_keys, duplicate_key_table
from reconsi.schema.compare import diff_schemas
from reconsi.schema.inspect import ColumnSchema, TableSchema

HEAD_ROWS = 10_000

# Shortcut keyword arguments that configure ``defaults`` (all columns).
_DEFAULT_OPTION_NAMES = (
    "absolute_tolerance",
    "relative_tolerance",
    "decimals",
    "normalize",
    "timezone",
    "tolerance_seconds",
    "compare_as_date",
    "null_equals_null",
    "empty_string_as_null",
)


def _schema(backend: TableBackend, side: Side, head: pd.DataFrame, name: str) -> TableSchema:
    nulls = backend.null_counts(side)
    cols = [
        ColumnSchema(
            name=c,
            dtype=str(head[c].dtype),
            logical_type=logical_type(head[c]),
            position=i,
            null_count=nulls.get(c, 0),
            nullable=nulls.get(c, 0) > 0,
        )
        for i, c in enumerate(backend.columns(side))
    ]
    return TableSchema(name=name, row_count=backend.row_count(side), columns=cols)


class Reconciliation:
    """A configured reconciliation job.

    >>> job = Reconciliation(left=left_df, right=right_df, keys=["id"])  # doctest: +SKIP
    >>> result = job.run()  # doctest: +SKIP

    Any :class:`~reconsi.configuration.ReconConfig` field can be passed as a keyword argument.
    ``absolute_tolerance``, ``relative_tolerance``, ``normalize`` (and other per-column options)
    given here apply to every compared column unless overridden in ``columns``.
    """

    def __init__(
        self,
        left: Any = None,
        right: Any = None,
        keys: str | Sequence[str] | None = None,
        compare_columns: Sequence[str] | None = None,
        *,
        config: ReconConfig | None = None,
        base_dir: str | Path | None = None,
        **options: Any,
    ) -> None:
        data: dict[str, Any] = (
            config.model_dump(exclude_unset=True, by_alias=True) if config is not None else {}
        )
        if keys is not None:
            data["keys"] = [keys] if isinstance(keys, str) else list(keys)
        if compare_columns is not None:
            data["compare_columns"] = list(compare_columns)
        defaults = dict(data.get("defaults") or {})
        for name in _DEFAULT_OPTION_NAMES:
            if name in options:
                defaults[name] = options.pop(name)
        if defaults:
            data["defaults"] = defaults
        data.update(options)
        self.config = config_from_dict(data)
        self.base_dir = Path(base_dir) if base_dir is not None else None
        self.left = self._source(left, self.config.left, "left")
        self.right = self._source(right, self.config.right, "right")

    def _source(self, obj: Any, spec: SourceConfig | None, side: str) -> TableSource:
        if isinstance(obj, dict):
            spec, obj = SourceConfig.model_validate(obj), None
        if obj is not None:
            name = Path(obj).name if isinstance(obj, str | Path) else side
            return as_source(obj, name, base_dir=self.base_dir)
        if spec is None:
            raise ConfigurationError(f"no {side} dataset: pass `{side}=` or set `{side}.path`")
        return as_source(
            spec.path,
            spec.name or Path(spec.path).name,
            format=spec.format,
            read_options=spec.read_options,
            base_dir=self.base_dir,
        )

    def run(self) -> ReconciliationResult:
        backend = make_backend(self.config.backend)
        try:
            return _Run(self.config, self.left, self.right, backend).execute()
        finally:
            backend.close()


def reconcile(
    left: Any,
    right: Any,
    keys: str | Sequence[str] | None = None,
    compare_columns: Sequence[str] | None = None,
    **options: Any,
) -> ReconciliationResult:
    """Reconcile two datasets and return a :class:`ReconciliationResult`.

    ``left``/``right`` may be DataFrames or paths to CSV, Parquet or JSON files.
    """
    return Reconciliation(left, right, keys, compare_columns, **options).run()


class _Run:
    def __init__(
        self, cfg: ReconConfig, left: TableSource, right: TableSource, backend: TableBackend
    ) -> None:
        self.cfg = cfg
        self.left = left
        self.right = right
        self.b = backend
        self.notes: list[dict[str, Any]] = []

    def note(self, kind: str, message: str, **data: Any) -> None:
        self.notes.append({"kind": kind, "message": message, **data})

    def _require(self, side: Side, columns: list[str], what: str) -> None:
        available = self.b.columns(side)
        missing = [c for c in columns if c not in available]
        if missing:
            raise ConfigurationError(
                f"{what} {missing} not found in the {side} dataset; available: {available}"
            )

    def execute(self) -> ReconciliationResult:
        cfg, b = self.cfg, self.b
        started = datetime.now(UTC)
        t0 = time.perf_counter()
        keys = cfg.resolved_left_keys
        rkeys = cfg.resolved_right_keys
        rename_right = {r: lft for lft, r in cfg.column_mapping.items()}
        rename_right.update({rk: lk for lk, rk in zip(keys, rkeys, strict=True)})
        rename_right = {r: lft for r, lft in rename_right.items() if r != lft}
        display_mapping = {lft: r for r, lft in rename_right.items()}

        b.load("left", self.left, rename={}, string_columns=keys)
        b.load("right", self.right, rename=rename_right, string_columns=rkeys)
        for side in SIDES:
            cols = b.columns(side)
            dupes = sorted({c for c in cols if cols.count(c) > 1})
            if dupes:
                raise ConfigurationError(
                    f"column mapping produces duplicate column names in the {side} dataset: {dupes}"
                )
        self._require("left", keys, "key columns")
        self._require("right", keys, "key columns (after mapping)")

        lhead, rhead = b.head("left", HEAD_ROWS), b.head("right", HEAD_ROWS)
        schema = diff_schemas(
            _schema(b, "left", lhead, self.left.name),
            _schema(b, "right", rhead, self.right.name),
            column_mapping=display_mapping,
            left_sample=lhead,
            right_sample=rhead,
            suggest=cfg.suggest_columns,
        )
        left_rows, right_rows = b.row_count("left"), b.row_count("right")

        self._apply_grain(keys)
        compare = self._compare_columns(keys)
        self._align_key_types(keys)

        key_frames = (b.fetch("left", keys), b.fetch("right", keys))
        key_analysis = analyze_keys(*key_frames, keys)
        duplicates = duplicate_key_table(*key_frames, keys)
        del key_frames

        join_keys, compare, ambiguous = self._apply_duplicate_strategy(
            keys, compare, key_analysis.left.is_unique and key_analysis.right.is_unique, duplicates
        )

        lhead, rhead = b.head("left", HEAD_ROWS), b.head("right", HEAD_ROWS)
        lcols, rcols = b.columns("left"), b.columns("right")
        all_cols = lcols + [c for c in rcols if c not in lcols]
        all_cols = [c for c in all_cols if c not in (OCCURRENCE, ROW_COUNT)]
        date_column = self._date_column(keys, all_cols, lhead, rhead)
        dimensions = self._dimensions(keys, all_cols, date_column, lhead, rhead)

        options = {c: cfg.column_options(c) for c in compare}
        kinds: dict[str, str] = {}
        dtype_mismatch: dict[str, bool] = {}
        dtypes: dict[str, tuple[str, str]] = {}
        for c in compare:
            kinds[c], dtype_mismatch[c] = resolve_kind(lhead[c], rhead[c], options[c])
            dtypes[c] = (str(lhead[c].dtype), str(rhead[c].dtype))

        left_columns = [c for c in lcols if c not in join_keys]
        right_columns = [c for c in rcols if c not in join_keys]
        acc = RecordAccumulator(
            keys=join_keys,
            compare_columns=compare,
            options=options,
            kinds=kinds,
            dtypes=dtypes,
            dtype_mismatch=dtype_mismatch,
            dimensions=dimensions,
            date_column=date_column,
            left_columns=left_columns,
            right_columns=right_columns,
            max_detail_rows=cfg.max_detail_rows,
        )
        for chunk in b.join(join_keys, left_columns, right_columns, cfg.chunk_size):
            acc.add(chunk)
        acc.finalize()
        records = acc.records()
        if acc.mismatch_rows_total > cfg.max_detail_rows:
            self.note(
                "truncated",
                f"Only the first {cfg.max_detail_rows:,} of {acc.mismatch_rows_total:,} value "
                "mismatches were retained in detail; counts and statistics use all of them.",
            )

        summary = self._summary(
            records, acc, ambiguous, key_analysis, compare, join_keys, left_rows, right_rows
        )
        status = Status.PASS
        if summary["missing_left"] or summary["missing_right"] or summary["value_mismatch_records"]:
            status = Status.FAIL
        metadata = {
            "reconsi_version": __version__,
            "python_version": platform.python_version(),
            "platform": platform.platform(terse=True),
            "started_at": started.isoformat(),
            "duration_seconds": round(time.perf_counter() - t0, 4),
            "backend": b.name,
            "left": self.left.describe(),
            "right": self.right.describe(),
            "seed": cfg.seed,
            "date_column": date_column,
            "dimensions": dimensions,
        }
        return ReconciliationResult(
            config=cfg,
            status=status,
            summary=summary,
            schema=schema,
            keys=key_analysis,
            columns=acc.columns,
            records=records,
            value_mismatches=acc.mismatches(),
            missing_left=acc.missing("left"),
            missing_right=acc.missing("right"),
            ambiguous=ambiguous,
            duplicate_keys=duplicates,
            metadata=metadata,
            notes=self.notes,
        )

    # ------------------------------------------------------------------ preparation steps
    def _apply_grain(self, keys: list[str]) -> None:
        cfg = self.cfg
        group_bys = (cfg.left_group_by, cfg.right_group_by)
        for side, group_by in zip(SIDES, group_bys, strict=True):
            if not group_by:
                continue
            before = self.b.row_count(side)
            self.b.aggregate(side, keys, cfg.aggregations)
            self.note(
                "aggregated",
                f"The {side} dataset was aggregated from {before:,} rows to "
                f"{self.b.row_count(side):,} by {keys} before comparison.",
                side=side,
                aggregations=dict(cfg.aggregations),
            )

    def _compare_columns(self, keys: list[str]) -> list[str]:
        cfg, b = self.cfg, self.b
        lcols, rcols = b.columns("left"), b.columns("right")
        if cfg.compare_columns is not None:
            self._require("left", cfg.compare_columns, "compare columns")
            self._require("right", cfg.compare_columns, "compare columns (after mapping)")
            bad = [c for c in cfg.compare_columns if c in keys]
            if bad:
                raise ConfigurationError(f"key columns cannot also be compare columns: {bad}")
            return list(cfg.compare_columns)
        if cfg.left_group_by or cfg.right_group_by:
            candidates = [c for c in cfg.aggregations if c in lcols and c in rcols]
        else:
            candidates = [c for c in lcols if c in rcols and c not in keys]
        return [c for c in candidates if c not in cfg.exclude_columns]

    def _align_key_types(self, keys: list[str]) -> None:
        lhead, rhead = self.b.head("left", HEAD_ROWS), self.b.head("right", HEAD_ROWS)
        differing = []
        for k in keys:
            lt, rt = logical_type(lhead[k]), logical_type(rhead[k])
            if lt != rt and "empty" not in (lt, rt):
                differing.append({"column": k, "left": lt, "right": rt})
        if differing:
            for side in SIDES:
                self.b.cast_keys_to_text(side, keys)
            self.note(
                "keys_cast_to_text",
                "Key columns have different types on each side, so keys were compared as "
                "canonical text (1, 1.0 and '1' are equal; '001' is not).",
                columns=differing,
            )
        if self.cfg.key_normalize:
            for side in SIDES:
                self.b.normalize_keys(side, keys, list(self.cfg.key_normalize))
            self.note(
                "keys_normalized",
                f"Key values were normalised before matching: {list(self.cfg.key_normalize)}.",
            )

    def _apply_duplicate_strategy(
        self,
        keys: list[str],
        compare: list[str],
        unique: bool,
        duplicates: pd.DataFrame,
    ) -> tuple[list[str], list[str], pd.DataFrame]:
        cfg, b = self.cfg, self.b
        strategy = cfg.duplicate_strategy
        ambiguous = pd.DataFrame(columns=[*keys, "_source"])
        if strategy in (DuplicateStrategy.AGGREGATE, DuplicateStrategy.GROUPED):
            aggs = dict(cfg.aggregations) or default_aggregations(
                b.head("left", HEAD_ROWS), compare
            )
            if strategy == DuplicateStrategy.GROUPED:
                aggs[ROW_COUNT] = "size"
            for side in SIDES:
                b.aggregate(side, keys, aggs)
            new_compare = [c for c in aggs if c in b.columns("left") and c in b.columns("right")]
            dropped = [c for c in compare if c not in new_compare]
            self.note(
                "aggregated",
                f"Both datasets were aggregated per key ({strategy.value} strategy).",
                aggregations=aggs,
                not_compared=dropped,
            )
            return keys, new_compare, ambiguous
        if unique:
            return keys, compare, ambiguous
        if strategy == DuplicateStrategy.STRICT:
            parts = []
            for side in SIDES:
                removed = b.remove_keys(side, keys, duplicates[keys])
                parts.append(removed.assign(_source=side))
            ambiguous = pd.concat(parts, ignore_index=True)
            self.note(
                "ambiguous",
                f"{len(duplicates):,} duplicated keys ({len(ambiguous):,} rows) were set aside "
                "because the strict strategy does not guess how duplicate rows pair up. Use "
                "duplicate_strategy first/last/aggregate/multiset to reconcile them.",
            )
        elif strategy in (DuplicateStrategy.FIRST, DuplicateStrategy.LAST):
            keep: Literal["first", "last"] = (
                "first" if strategy == DuplicateStrategy.FIRST else "last"
            )
            removed = {side: b.deduplicate(side, keys, keep) for side in SIDES}
            self.note(
                "deduplicated",
                f"Kept the {strategy.value} row per key; removed {removed['left']:,} left and "
                f"{removed['right']:,} right duplicate rows.",
            )
        elif strategy == DuplicateStrategy.MULTISET:
            for side in SIDES:
                b.add_occurrence(side, keys, compare)
            self.note(
                "multiset",
                "Duplicate rows were paired within each key by sorted value order "
                "(identical rows pair first); unpaired occurrences are reported as missing.",
            )
            return [*keys, OCCURRENCE], compare, ambiguous
        return keys, compare, ambiguous

    def _date_column(
        self, keys: list[str], all_cols: list[str], lhead: pd.DataFrame, rhead: pd.DataFrame
    ) -> str | None:
        if self.cfg.date_column is not None:
            if self.cfg.date_column not in all_cols:
                raise ConfigurationError(f"date_column {self.cfg.date_column!r} not found")
            return self.cfg.date_column
        return detect_date_column([lhead, rhead], keys + [c for c in all_cols if c not in keys])

    def _dimensions(
        self,
        keys: list[str],
        all_cols: list[str],
        date_column: str | None,
        lhead: pd.DataFrame,
        rhead: pd.DataFrame,
    ) -> list[str]:
        cfg = self.cfg
        if cfg.dimensions is not None:
            missing = [d for d in cfg.dimensions if d not in all_cols]
            if missing:
                raise ConfigurationError(f"dimensions {missing} not found in either dataset")
            return list(cfg.dimensions)
        candidates = (keys if len(keys) > 1 else []) + [c for c in all_cols if c not in keys]
        return detect_dimensions(
            [lhead, rhead],
            candidates,
            exclude={date_column} if date_column else set(),
            max_dimensions=cfg.max_dimensions,
            max_levels=cfg.max_dimension_levels,
        )

    def _summary(
        self,
        records: pd.DataFrame,
        acc: RecordAccumulator,
        ambiguous: pd.DataFrame,
        key_analysis: Any,
        compare: list[str],
        join_keys: list[str],
        left_rows: int,
        right_rows: int,
    ) -> dict[str, Any]:
        counts = records[STATUS].value_counts() if not records.empty else pd.Series(dtype=int)

        def count(s: RecordStatus) -> int:
            return int(counts.get(s.value, 0))

        matched = count(RecordStatus.MATCHED)
        value_mismatch = count(RecordStatus.VALUE_MISMATCH)
        missing_left = count(RecordStatus.MISSING_LEFT)
        missing_right = count(RecordStatus.MISSING_RIGHT)
        total = matched + value_mismatch + missing_left + missing_right
        compared = matched + value_mismatch

        def pct(n: int, d: int) -> float:
            return 100.0 * n / d if d else 0.0

        return {
            "left_rows": left_rows,
            "right_rows": right_rows,
            "left_records": self.b.row_count("left"),
            "right_records": self.b.row_count("right"),
            "keys": join_keys,
            "duplicate_strategy": self.cfg.duplicate_strategy.value,
            "total_records": total,
            "compared_records": compared,
            "matched_records": matched,
            "value_mismatch_records": value_mismatch,
            "missing_left": missing_left,
            "missing_right": missing_right,
            "missing_records": missing_left + missing_right,
            "ambiguous_records": len(ambiguous),
            "duplicate_keys_left": key_analysis.left.duplicate_keys,
            "duplicate_keys_right": key_analysis.right.duplicate_keys,
            "match_percentage": pct(matched, total),
            "mismatch_percentage": pct(value_mismatch, compared),
            "missing_percentage": pct(missing_left + missing_right, total),
            "columns_compared": len(compare),
            "columns_with_mismatches": sum(1 for s in acc.columns.values() if s.mismatches),
            "value_mismatches": sum(s.mismatches for s in acc.columns.values()),
        }
