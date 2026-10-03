"""Compare the schemas of two datasets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from reconsi.core.dtypes import compatible_types
from reconsi.schema.inspect import TableSchema, inspect_schema
from reconsi.schema.matching import ColumnMatchSuggestion, suggest_column_matches


@dataclass(frozen=True)
class DtypeChange:
    column: str
    left_dtype: str
    right_dtype: str
    left_logical: str
    right_logical: str
    compatible: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "left_dtype": self.left_dtype,
            "right_dtype": self.right_dtype,
            "left_logical_type": self.left_logical,
            "right_logical_type": self.right_logical,
            "compatible": self.compatible,
        }


@dataclass(frozen=True)
class SchemaDiff:
    left: TableSchema
    right: TableSchema
    common: list[str]
    added: list[str]
    """Columns only in the right dataset."""
    removed: list[str]
    """Columns only in the left dataset."""
    renamed: dict[str, str]
    """Explicit ``left -> right`` renames from the user's column mapping."""
    dtype_changes: list[DtypeChange]
    nullability_changes: list[dict[str, Any]]
    order_changed: bool
    suggestions: list[ColumnMatchSuggestion] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return not (
            self.added
            or self.removed
            or self.dtype_changes
            or self.nullability_changes
            or self.order_changed
        )

    @property
    def change_count(self) -> int:
        return len(self.added) + len(self.removed) + len(self.dtype_changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "identical": self.identical,
            "common_columns": self.common,
            "added_columns": self.added,
            "removed_columns": self.removed,
            "renamed_columns": self.renamed,
            "dtype_changes": [c.to_dict() for c in self.dtype_changes],
            "nullability_changes": self.nullability_changes,
            "order_changed": self.order_changed,
            "suggested_column_matches": [s.to_dict() for s in self.suggestions],
        }


def compare_schemas(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    column_mapping: dict[str, str] | None = None,
    left_name: str = "left",
    right_name: str = "right",
    suggest: bool = True,
) -> SchemaDiff:
    """Compare two datasets' schemas.

    ``column_mapping`` maps left column names to right column names. Right columns are reported
    under their left (mapped) names so that common columns line up.
    """
    mapping = dict(column_mapping or {})
    inverse = {r: lft for lft, r in mapping.items()}
    renamed_right = right.rename(columns=inverse)
    ls = inspect_schema(left, left_name)
    rs_raw = inspect_schema(right, right_name)
    rs = inspect_schema(renamed_right, right_name)
    lnames, rnames = ls.column_names, rs.column_names
    rset, lset = set(rnames), set(lnames)
    common = [c for c in lnames if c in rset]
    added = [c for c in rnames if c not in lset]
    removed = [c for c in lnames if c not in rset]
    dtype_changes: list[DtypeChange] = []
    nullability: list[dict[str, Any]] = []
    for col in common:
        lc, rc = ls.column(col), rs.column(col)
        if lc.logical_type != rc.logical_type or lc.dtype != rc.dtype:
            dtype_changes.append(
                DtypeChange(
                    col,
                    lc.dtype,
                    rc.dtype,
                    lc.logical_type,
                    rc.logical_type,
                    compatible_types(lc.logical_type, rc.logical_type),
                )
            )
        if lc.nullable != rc.nullable:
            nullability.append(
                {
                    "column": col,
                    "left_null_count": lc.null_count,
                    "right_null_count": rc.null_count,
                }
            )
    order_changed = [c for c in lnames if c in rset] != [c for c in rnames if c in lset]
    suggestions: list[ColumnMatchSuggestion] = []
    if suggest and removed and added:
        suggestions = suggest_column_matches(left, renamed_right, removed, added)
    return SchemaDiff(
        left=ls,
        right=rs_raw,
        common=common,
        added=added,
        removed=removed,
        renamed={k: v for k, v in mapping.items() if k in lset},
        dtype_changes=dtype_changes,
        nullability_changes=nullability,
        order_changed=order_changed,
        suggestions=suggestions,
    )
