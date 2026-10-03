"""Compute backends: pandas (default) and DuckDB (optional, for larger-than-memory data)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reconsi.backends.base import TableBackend
from reconsi.backends.pandas_backend import PandasBackend
from reconsi.core.errors import ConfigurationError


def make_backend(name: str, options: Mapping[str, Any] | None = None) -> TableBackend:
    if name == "pandas":
        return PandasBackend()
    if name == "duckdb":
        from reconsi.backends.duckdb_backend import DuckDBBackend

        return DuckDBBackend(options)
    raise ConfigurationError(f"unknown backend {name!r}; choose 'pandas' or 'duckdb'")


__all__ = ["PandasBackend", "TableBackend", "make_backend"]
