"""Compute backends: pandas (default) and DuckDB (optional, for larger-than-memory data)."""

from __future__ import annotations

from reconsi.backends.base import TableBackend
from reconsi.backends.pandas_backend import PandasBackend
from reconsi.core.errors import ConfigurationError


def make_backend(name: str) -> TableBackend:
    if name == "pandas":
        return PandasBackend()
    raise ConfigurationError(f"unknown backend {name!r}")


__all__ = ["PandasBackend", "TableBackend", "make_backend"]
