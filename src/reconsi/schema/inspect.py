"""Describe the structure of a single dataset."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from reconsi.core.dtypes import logical_type


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    dtype: str
    logical_type: str
    position: int
    null_count: int
    nullable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "logical_type": self.logical_type,
            "position": self.position,
            "null_count": self.null_count,
            "nullable": self.nullable,
        }


@dataclass(frozen=True)
class TableSchema:
    name: str
    row_count: int
    columns: list[ColumnSchema] = field(default_factory=list)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column(self, name: str) -> ColumnSchema:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "row_count": self.row_count,
            "column_count": len(self.columns),
            "columns": [c.to_dict() for c in self.columns],
        }


def inspect_schema(frame: pd.DataFrame, name: str = "table") -> TableSchema:
    """Return column names, dtypes, logical types and nullability for ``frame``."""
    nulls = frame.isna().sum()
    columns = [
        ColumnSchema(
            name=str(col),
            dtype=str(frame[col].dtype),
            logical_type=logical_type(frame[col]),
            position=i,
            null_count=int(nulls[col]),
            nullable=bool(nulls[col] > 0),
        )
        for i, col in enumerate(frame.columns)
    ]
    return TableSchema(name=name, row_count=len(frame), columns=columns)
