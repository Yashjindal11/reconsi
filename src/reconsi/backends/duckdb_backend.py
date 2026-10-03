"""DuckDB backend for datasets that are large relative to memory.

Inputs are loaded into DuckDB tables (which spill to disk under memory pressure); aggregation,
de-duplication and the full outer join run in SQL and the join is streamed back to Python in
Arrow record batches. Value comparison then uses exactly the same code as the pandas backend.

All identifiers are quoted and file paths are passed to DuckDB's reader functions as values,
never interpolated into SQL text.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator, Mapping
from typing import Any, ClassVar, Literal

import pandas as pd

from reconsi.backends.base import (
    JOIN_STATUS,
    LEFT_PREFIX,
    OCCURRENCE,
    RIGHT_PREFIX,
    Side,
    TableBackend,
)
from reconsi.comparison.values import apply_normalizations
from reconsi.core.errors import BackendUnavailableError, ConfigurationError, InputError
from reconsi.inputs.sources import TableSource
from reconsi.keys.canonical import canonical_strings

ROW = "__reconsi_row"
NUMERIC_SQL = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
    "REAL",
)
ALLOWED_OPTIONS = frozenset({"memory_limit", "threads", "temp_directory"})

AGG_SQL = {
    "sum": "sum({c})",
    "count": "count({c})",
    "mean": "avg({c})",
    "median": "median({c})",
    "min": "min({c})",
    "max": "max({c})",
    "first": f'arg_min({{c}}, "{ROW}")',
    "last": f'arg_max({{c}}, "{ROW}")',
    "nunique": "count(DISTINCT {c})",
}


def q(name: str) -> str:
    """Quote an SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


class DuckDBBackend(TableBackend):
    name: ClassVar[str] = "duckdb"

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise BackendUnavailableError(
                'The DuckDB backend needs duckdb: pip install "reconsi[duckdb]"'
            ) from exc
        opts = dict(options or {})
        unknown = set(opts) - ALLOWED_OPTIONS
        if unknown:
            raise ConfigurationError(f"unknown DuckDB options {sorted(unknown)}")
        self._tmp = tempfile.TemporaryDirectory(prefix="reconsi-duckdb-")
        self.con = duckdb.connect(":memory:")
        self.con.execute("SET preserve_insertion_order = true")
        self.con.execute(
            "SET temp_directory = ?", [str(opts.get("temp_directory", self._tmp.name))]
        )
        if "memory_limit" in opts:
            self.con.execute("SET memory_limit = ?", [str(opts["memory_limit"])])
        if "threads" in opts:
            self.con.execute(f"SET threads = {int(opts['threads'])}")
        self._n = 0

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _t(side: Side) -> str:
        return q(f"t_{side}")

    def _tmp_name(self) -> str:
        self._n += 1
        return f"reconsi_tmp_{self._n}"

    def _describe(self, side: Side) -> list[tuple[str, str]]:
        rows = self.con.execute(f"DESCRIBE {self._t(side)}").fetchall()
        return [(str(r[0]), str(r[1])) for r in rows if r[0] != ROW]

    def _replace(self, side: Side, select_sql: str, params: list[Any] | None = None) -> None:
        self.con.execute(f"CREATE OR REPLACE TABLE {self._t(side)} AS {select_sql}", params or [])

    def _cols(self, columns: list[str]) -> str:
        return ", ".join(q(c) for c in columns)

    # ------------------------------------------------------------------ TableBackend
    def load(
        self,
        side: Side,
        source: TableSource,
        *,
        rename: Mapping[str, str],
        string_columns: list[str],
    ) -> None:
        if source.frame is not None:
            name = self._tmp_name()
            self.con.register(name, source.frame)
            rel = self.con.table(name)
        else:
            rel = self._read_file(source, string_columns)
        view = self._tmp_name()
        rel.create_view(view)
        cols = [str(c) for c in rel.columns]
        select = ", ".join(f"{q(c)} AS {q(rename[c])}" if c in rename else q(c) for c in cols)
        self._replace(side, f"SELECT {select}, row_number() OVER () AS {q(ROW)} FROM {q(view)}")

    def _read_file(self, source: TableSource, string_columns: list[str]) -> Any:
        assert source.path is not None
        path = str(source.path)
        opts = dict(source.read_options)
        try:
            if source.format == "parquet":
                return self.con.read_parquet(path)
            if source.format == "csv":
                kwargs: dict[str, Any] = {}
                if string_columns:
                    kwargs["dtype"] = {c: "VARCHAR" for c in string_columns}
                sep = opts.get("sep") or opts.get("delimiter")
                if sep is None and source.path.suffix.lower() == ".tsv":
                    sep = "\t"
                if sep:
                    kwargs["sep"] = sep
                if "encoding" in opts:
                    kwargs["encoding"] = opts["encoding"]
                try:
                    return self.con.read_csv(path, **kwargs)
                except Exception:
                    kwargs.pop("dtype", None)
                    return self.con.read_csv(path, **kwargs)
            if source.format == "jsonl":
                return self.con.read_json(path, format="newline_delimited")
            if source.format == "json":
                return self.con.read_json(path, format="auto")
        except Exception as exc:
            raise InputError(f"DuckDB could not read {path}: {exc}") from exc
        # Other formats (e.g. Excel) go through pandas.
        frame = source.to_pandas(string_columns=string_columns)
        name = self._tmp_name()
        self.con.register(name, frame)
        return self.con.table(name)

    def columns(self, side: Side) -> list[str]:
        return [c for c, _ in self._describe(side)]

    def row_count(self, side: Side) -> int:
        row = self.con.execute(f"SELECT count(*) FROM {self._t(side)}").fetchone()
        assert row is not None
        return int(row[0])

    def head(self, side: Side, n: int) -> pd.DataFrame:
        cols = self._cols(self.columns(side))
        return self.con.execute(
            f"SELECT {cols} FROM {self._t(side)} ORDER BY {q(ROW)} LIMIT {int(n)}"
        ).df()

    def null_counts(self, side: Side) -> dict[str, int]:
        cols = self.columns(side)
        if not cols:
            return {}
        exprs = ", ".join(f"count(*) - count({q(c)})" for c in cols)
        row = self.con.execute(f"SELECT {exprs} FROM {self._t(side)}").fetchone()
        assert row is not None
        return {c: int(v) for c, v in zip(cols, row, strict=True)}

    def fetch(self, side: Side, columns: list[str]) -> pd.DataFrame:
        return self.con.execute(
            f"SELECT {self._cols(columns)} FROM {self._t(side)} ORDER BY {q(ROW)}"
        ).df()

    def sample(self, side: Side, columns: list[str], n: int, seed: int) -> pd.DataFrame:
        if not columns:
            return pd.DataFrame()
        if self.row_count(side) <= n:
            return self.fetch(side, columns)
        return self.con.execute(
            f"SELECT {self._cols(columns)} FROM {self._t(side)} "
            f"USING SAMPLE reservoir({int(n)} ROWS) REPEATABLE ({int(seed)})"
        ).df()

    def sums(self, side: Side, columns: list[str]) -> dict[str, float | None]:
        types = dict(self._describe(side))
        numeric = [c for c in columns if c in types and types[c].upper().startswith(NUMERIC_SQL)]
        out: dict[str, float | None] = {c: None for c in columns}
        if numeric:
            exprs = ", ".join(f"coalesce(sum(CAST({q(c)} AS DOUBLE)), 0)" for c in numeric)
            row = self.con.execute(f"SELECT {exprs} FROM {self._t(side)}").fetchone()
            assert row is not None
            out.update({c: float(v) for c, v in zip(numeric, row, strict=True)})
        return out

    def aggregate(self, side: Side, keys: list[str], aggregations: Mapping[str, str]) -> None:
        cols = set(self.columns(side))
        exprs = []
        for col, fn in aggregations.items():
            if fn == "size" or (fn == "count" and col not in cols):
                exprs.append(f"count(*) AS {q(col)}")
            elif col not in cols:
                raise ConfigurationError(
                    f"aggregation column {col!r} not found; available columns: {sorted(cols)}"
                )
            else:
                exprs.append(f"{AGG_SQL[fn].format(c=q(col))} AS {q(col)}")
        k = self._cols(keys)
        self._replace(
            side,
            f"SELECT {k}, {', '.join(exprs)}, row_number() OVER (ORDER BY {k}) AS {q(ROW)} "
            f"FROM {self._t(side)} GROUP BY {k} ORDER BY {k}",
        )

    def deduplicate(self, side: Side, keys: list[str], keep: Literal["first", "last"]) -> int:
        before = self.row_count(side)
        order = "ASC" if keep == "first" else "DESC"
        self._replace(
            side,
            f"SELECT * EXCLUDE (_rk) FROM (SELECT *, row_number() OVER (PARTITION BY "
            f"{self._cols(keys)} ORDER BY {q(ROW)} {order}) AS _rk FROM {self._t(side)}) "
            f"WHERE _rk = 1 ORDER BY {q(ROW)}",
        )
        return before - self.row_count(side)

    def remove_keys(self, side: Side, keys: list[str], key_values: pd.DataFrame) -> pd.DataFrame:
        if key_values.empty:
            return self.head(side, 0)
        name = self._tmp_name()
        self.con.register(name, key_values[keys].drop_duplicates())
        on = " AND ".join(f"t.{q(k)} = kv.{q(k)}" for k in keys)
        removed = self.con.execute(
            f"SELECT {', '.join('t.' + q(c) for c in self.columns(side))} FROM {self._t(side)} t "
            f"SEMI JOIN {q(name)} kv ON {on} ORDER BY t.{q(ROW)}"
        ).df()
        self._replace(
            side,
            f"SELECT t.* FROM {self._t(side)} t ANTI JOIN {q(name)} kv ON {on} ORDER BY t.{q(ROW)}",
        )
        return removed

    def add_occurrence(self, side: Side, keys: list[str], order_by: list[str]) -> None:
        present = set(self.columns(side))
        order = [f"{q(c)} ASC NULLS LAST" for c in order_by if c in present] + [q(ROW)]
        self._replace(
            side,
            f"SELECT *, row_number() OVER (PARTITION BY {self._cols(keys)} ORDER BY "
            f"{', '.join(order)}) - 1 AS {q(OCCURRENCE)} FROM {self._t(side)}",
        )

    def _rewrite_keys(self, side: Side, keys: list[str], transform: Any) -> None:
        frame = self.fetch(side, [*keys, ROW])
        for k in keys:
            frame[k] = transform(frame[k])
        name = self._tmp_name()
        self.con.register(name, frame.astype({k: object for k in keys}))
        replaced = ", ".join(f"CAST(c.{q(k)} AS VARCHAR) AS {q(k)}" for k in keys)
        self._replace(
            side,
            f"SELECT t.* REPLACE ({replaced}) FROM {self._t(side)} t JOIN {q(name)} c "
            f"USING ({q(ROW)}) ORDER BY t.{q(ROW)}",
        )

    def cast_keys_to_text(self, side: Side, keys: list[str]) -> None:
        self._rewrite_keys(side, keys, canonical_strings)

    def normalize_keys(self, side: Side, keys: list[str], steps: list[str]) -> None:
        def transform(series: pd.Series) -> pd.Series:
            text = canonical_strings(series)
            mask = text.isna().to_numpy()
            out = apply_normalizations(text.fillna("").astype(object), steps).astype(object)
            out[mask] = None
            return out

        self._rewrite_keys(side, keys, transform)

    def join(
        self,
        keys: list[str],
        left_columns: list[str],
        right_columns: list[str],
        chunk_size: int,
    ) -> Iterator[pd.DataFrame]:
        key_sql = ", ".join(f"coalesce(l.{q(k)}, r.{q(k)}) AS {q(k)}" for k in keys)
        on = " AND ".join(f"l.{q(k)} = r.{q(k)}" for k in keys)
        side = (
            f"CASE WHEN l.{q(ROW)} IS NULL THEN 'right_only' "
            f"WHEN r.{q(ROW)} IS NULL THEN 'left_only' ELSE 'both' END AS {q(JOIN_STATUS)}"
        )
        values = [f"l.{q(c)} AS {q(LEFT_PREFIX + c)}" for c in left_columns]
        values += [f"r.{q(c)} AS {q(RIGHT_PREFIX + c)}" for c in right_columns]
        sql = (
            f"SELECT {', '.join([key_sql, side, *values])} FROM {self._t('left')} l "
            f"FULL OUTER JOIN {self._t('right')} r ON {on} "
            f"ORDER BY l.{q(ROW)} NULLS LAST, r.{q(ROW)}"
        )
        result = self.con.execute(sql)
        to_reader = getattr(result, "to_arrow_reader", None)
        reader = (
            to_reader(chunk_size)
            if to_reader is not None
            else result.fetch_record_batch(rows_per_batch=chunk_size)
        )
        produced = False
        for batch in reader:
            produced = True
            yield batch.to_pandas()
        if not produced:
            yield reader.schema.empty_table().to_pandas()

    def close(self) -> None:
        try:
            self.con.close()
        finally:
            self._tmp.cleanup()
