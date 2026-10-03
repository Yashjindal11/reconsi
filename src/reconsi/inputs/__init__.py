"""Dataset inputs: DataFrames, CSV, Parquet, JSON (and adapters via ``register_reader``)."""

from reconsi.inputs.sources import (
    TableSource,
    as_source,
    detect_format,
    load_table,
    register_reader,
    resolve_path,
)

__all__ = [
    "TableSource",
    "as_source",
    "detect_format",
    "load_table",
    "register_reader",
    "resolve_path",
]
