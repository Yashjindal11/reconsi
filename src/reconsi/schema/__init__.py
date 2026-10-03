"""Schema inspection, schema comparison and column-match suggestions."""

from reconsi.schema.compare import DtypeChange, SchemaDiff, compare_schemas
from reconsi.schema.inspect import ColumnSchema, TableSchema, inspect_schema
from reconsi.schema.matching import (
    ColumnMatchSuggestion,
    name_similarity,
    normalized_name,
    suggest_column_matches,
)

__all__ = [
    "ColumnMatchSuggestion",
    "ColumnSchema",
    "DtypeChange",
    "SchemaDiff",
    "TableSchema",
    "compare_schemas",
    "inspect_schema",
    "name_similarity",
    "normalized_name",
    "suggest_column_matches",
]
