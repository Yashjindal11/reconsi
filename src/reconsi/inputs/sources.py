"""Table input abstraction.

Every dataset handed to ReconSI becomes a :class:`TableSource`. A source knows *where* the data
lives (an in-memory frame or a file) but defers reading until a backend asks for it, so that the
DuckDB backend can scan files directly without first materialising them in pandas.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from reconsi.core.errors import InputError

FORMAT_BY_SUFFIX: dict[str, str] = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".xlsx": "excel",
    ".xls": "excel",
}

# Only these reader options may be passed through configuration files. Anything else (for example
# ``storage_options`` or custom converters) could reach the network or execute code.
ALLOWED_READ_OPTIONS: dict[str, frozenset[str]] = {
    "csv": frozenset(
        {
            "sep",
            "delimiter",
            "encoding",
            "decimal",
            "thousands",
            "header",
            "skiprows",
            "nrows",
            "na_values",
            "keep_default_na",
            "quotechar",
            "comment",
            "usecols",
            "dtype",
        }
    ),
    "parquet": frozenset({"columns"}),
    "json": frozenset({"orient", "encoding", "dtype"}),
    "jsonl": frozenset({"encoding", "dtype"}),
    "excel": frozenset({"sheet_name", "header", "skiprows", "nrows", "usecols", "dtype"}),
}

Reader = Callable[[Path, Mapping[str, Any]], pd.DataFrame]


def _read_csv(path: Path, options: Mapping[str, Any]) -> pd.DataFrame:
    opts = dict(options)
    if path.suffix.lower() == ".tsv" and "sep" not in opts and "delimiter" not in opts:
        opts["sep"] = "\t"
    return pd.read_csv(path, **opts)


def _read_parquet(path: Path, options: Mapping[str, Any]) -> pd.DataFrame:
    try:
        return pd.read_parquet(path, **dict(options))
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise InputError(
            'Reading Parquet requires pyarrow: pip install "reconsi[parquet]"'
        ) from exc


def _read_json(path: Path, options: Mapping[str, Any]) -> pd.DataFrame:
    return pd.read_json(path, **dict(options))


def _read_jsonl(path: Path, options: Mapping[str, Any]) -> pd.DataFrame:
    return pd.read_json(path, lines=True, **dict(options))


def _read_excel(path: Path, options: Mapping[str, Any]) -> pd.DataFrame:
    try:
        return pd.read_excel(path, **dict(options))
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise InputError("Reading Excel files requires openpyxl: pip install openpyxl") from exc


_READERS: dict[str, Reader] = {
    "csv": _read_csv,
    "parquet": _read_parquet,
    "json": _read_json,
    "jsonl": _read_jsonl,
    "excel": _read_excel,
}


def register_reader(fmt: str, reader: Reader, allowed_options: Iterable[str] = ()) -> None:
    """Register a reader for a new file format (an extension point for adapters)."""
    _READERS[fmt] = reader
    ALLOWED_READ_OPTIONS[fmt] = frozenset(allowed_options)


@dataclass(frozen=True)
class TableSource:
    """A lazily-read dataset."""

    name: str
    frame: pd.DataFrame | None = None
    path: Path | None = None
    format: str | None = None
    read_options: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_file(self) -> bool:
        return self.path is not None

    def to_pandas(self, string_columns: Iterable[str] = ()) -> pd.DataFrame:
        """Materialise the source as a pandas DataFrame.

        ``string_columns`` are read as text from CSV/JSON files so that identifiers such as
        ``00123`` keep their leading zeros instead of being silently parsed as integers.
        """
        if self.frame is not None:
            return self.frame
        assert self.path is not None and self.format is not None
        options = dict(self.read_options)
        cols = list(string_columns)
        if cols and self.format in {"csv", "excel", "json", "jsonl"}:
            dtype = dict(options.get("dtype") or {})
            for c in cols:
                dtype.setdefault(c, str)
            options["dtype"] = dtype
        try:
            frame = _READERS[self.format](self.path, options)
        except InputError:
            raise
        except Exception as exc:
            raise InputError(f"Could not read {self.path} as {self.format}: {exc}") from exc
        return frame

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "file" if self.path is not None else "dataframe",
            "path": str(self.path) if self.path is not None else None,
            "format": self.format or "dataframe",
        }


def detect_format(path: Path) -> str:
    fmt = FORMAT_BY_SUFFIX.get(path.suffix.lower())
    if fmt is None:
        raise InputError(
            f"Cannot infer the format of {path.name!r}; pass format= one of {sorted(_READERS)}"
        )
    return fmt


def resolve_path(raw: str | os.PathLike[str], base_dir: Path | None = None) -> Path:
    """Resolve a user-supplied path safely (local files only, no URLs)."""
    text = os.fspath(raw)
    if "://" in text:
        raise InputError(f"Only local files are supported, got {text!r}")
    path = Path(text).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    path = path.resolve()
    if not path.exists():
        raise InputError(f"Input file not found: {path}")
    if not path.is_file():
        raise InputError(f"Input path is not a file: {path}")
    return path


def as_source(
    obj: Any,
    name: str,
    *,
    format: str | None = None,
    read_options: Mapping[str, Any] | None = None,
    base_dir: Path | None = None,
) -> TableSource:
    """Wrap a DataFrame, Arrow table, Polars frame or file path as a :class:`TableSource`."""
    if isinstance(obj, TableSource):
        return obj
    if isinstance(obj, pd.DataFrame):
        return TableSource(name=name, frame=obj)
    if hasattr(obj, "to_pandas") and callable(obj.to_pandas):
        # pyarrow.Table, polars.DataFrame and similar expose ``to_pandas``.
        frame = obj.to_pandas()
        if not isinstance(frame, pd.DataFrame):
            raise InputError(f"{type(obj).__name__}.to_pandas() did not return a DataFrame")
        return TableSource(name=name, frame=frame)
    if isinstance(obj, str | os.PathLike):
        path = resolve_path(obj, base_dir)
        fmt = format or detect_format(path)
        if fmt not in _READERS:
            raise InputError(f"Unsupported format {fmt!r}; supported: {sorted(_READERS)}")
        options = dict(read_options or {})
        unknown = set(options) - ALLOWED_READ_OPTIONS.get(fmt, frozenset())
        if unknown:
            raise InputError(f"Read options not allowed for {fmt}: {sorted(unknown)}")
        return TableSource(name=name, path=path, format=fmt, read_options=options)
    raise InputError(
        f"Unsupported input type {type(obj).__name__}; pass a DataFrame or a CSV/Parquet/JSON path"
    )


def load_table(obj: Any, name: str = "table", **kwargs: Any) -> pd.DataFrame:
    """Convenience: read any supported input into a pandas DataFrame."""
    return as_source(obj, name, **kwargs).to_pandas()
