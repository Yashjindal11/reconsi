"""Validated configuration for a reconciliation job (Python API and YAML share this model)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reconsi.comparison.options import ColumnKind, ColumnOptions, StringNormalization
from reconsi.core.types import DuplicateStrategy

AggregationName = Literal[
    "sum", "count", "size", "mean", "median", "min", "max", "first", "last", "nunique"
]

RuleMetric = Literal[
    "missing_records",
    "missing_left_records",
    "missing_right_records",
    "missing_percentage",
    "mismatched_records",
    "mismatch_percentage",
    "match_percentage",
    "duplicate_keys",
    "ambiguous_records",
    "schema_changes",
    "column_mismatches",
    "column_mismatch_percentage",
    "column_total_difference",
    "column_total_relative_difference",
]

COLUMN_METRICS: frozenset[str] = frozenset(
    {
        "column_mismatches",
        "column_mismatch_percentage",
        "column_total_difference",
        "column_total_relative_difference",
    }
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceConfig(_Strict):
    path: str
    format: str | None = None
    name: str | None = None
    read_options: dict[str, Any] = Field(default_factory=dict)


class Thresholds(_Strict):
    """Limits that decide the overall status. Percentages are on a 0-100 scale."""

    max_missing_records: int | None = Field(default=None, ge=0)
    max_missing_percentage: float | None = Field(default=None, ge=0, le=100)
    max_mismatched_records: int | None = Field(default=None, ge=0)
    max_mismatch_percentage: float | None = Field(default=None, ge=0, le=100)
    max_duplicate_keys: int | None = Field(default=None, ge=0)
    max_schema_changes: int | None = Field(default=None, ge=0)


class RuleConfig(_Strict):
    """A named, reusable rule.

    A rule with a ``column`` and no ``metric`` checks that column's mismatches (default: none
    allowed). Comparison fields (``type``, tolerances, ``normalize`` ...) configure how that column
    is compared.
    """

    name: str
    metric: RuleMetric | None = None
    column: str | None = None
    max: float | None = None
    min: float | None = None
    severity: Literal["error", "warning"] = "error"
    description: str | None = None
    type: ColumnKind | None = None
    absolute_tolerance: float | None = Field(default=None, ge=0)
    relative_tolerance: float | None = Field(default=None, ge=0)
    decimals: int | None = Field(default=None, ge=0, le=15)
    normalize: list[StringNormalization] | None = None
    timezone: str | None = None
    tolerance_seconds: float | None = Field(default=None, ge=0)
    compare_as_date: bool | None = None
    null_equals_null: bool | None = None
    empty_string_as_null: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> RuleConfig:
        if self.metric is None and self.column is None:
            raise ValueError(f"rule {self.name!r}: set `metric`, `column`, or both")
        if self.metric in COLUMN_METRICS and self.column is None:
            raise ValueError(f"rule {self.name!r}: metric {self.metric} needs a `column`")
        return self

    @property
    def effective_metric(self) -> str:
        return self.metric or "column_mismatches"

    def column_options(self) -> ColumnOptions | None:
        fields = (
            "type",
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
        data = {f: getattr(self, f) for f in fields if getattr(self, f) is not None}
        return ColumnOptions(**data) if data else None


class OutputConfig(_Strict):
    html: str | None = None
    json_path: str | None = Field(default=None, alias="json")
    markdown: str | None = None
    export_dir: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class HistoryConfig(_Strict):
    enabled: bool = True
    path: str = ".reconsi/history.db"


class ReconConfig(_Strict):
    name: str = "reconciliation"
    description: str | None = None
    left: SourceConfig | None = None
    right: SourceConfig | None = None

    keys: list[str] = Field(default_factory=list)
    left_keys: list[str] | None = None
    right_keys: list[str] | None = None
    column_mapping: dict[str, str] = Field(default_factory=dict)
    """``left_column_name: right_column_name`` for columns named differently."""
    compare_columns: list[str] | None = None
    exclude_columns: list[str] = Field(default_factory=list)
    key_normalize: list[StringNormalization] = Field(default_factory=list)

    defaults: ColumnOptions = Field(default_factory=ColumnOptions)
    columns: dict[str, ColumnOptions] = Field(default_factory=dict)

    duplicate_strategy: DuplicateStrategy = DuplicateStrategy.STRICT
    aggregations: dict[str, AggregationName] = Field(default_factory=dict)
    left_group_by: list[str] | None = None
    right_group_by: list[str] | None = None

    dimensions: list[str] | None = None
    max_dimensions: int = Field(default=8, ge=0, le=50)
    max_dimension_levels: int = Field(default=50, ge=2)
    date_column: str | None = None
    time_frequency: Literal["D", "W", "M"] = "D"

    thresholds: Thresholds = Field(default_factory=Thresholds)
    rules: list[RuleConfig] = Field(default_factory=list)

    backend: Literal["pandas", "duckdb"] = "pandas"
    chunk_size: int = Field(default=1_000_000, ge=1_000)
    sample_size: int = Field(default=20, ge=0, le=10_000)
    max_detail_rows: int = Field(default=1_000_000, ge=0)
    distribution_sample: int = Field(default=200_000, ge=1_000)
    alpha: float = Field(default=0.01, gt=0, lt=0.5)
    seed: int = 0
    suggest_columns: bool = True

    output: OutputConfig | None = None
    history: HistoryConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _thresholds_under_rules(cls, data: Any) -> Any:
        # Accept the shorthand ``rules: {max_mismatch_percentage: 0.1}`` as thresholds.
        if isinstance(data, dict) and isinstance(data.get("rules"), dict):
            data = dict(data)
            thresholds = dict(data.get("thresholds") or {})
            thresholds.update(data.pop("rules"))
            data["thresholds"] = thresholds
        return data

    @model_validator(mode="after")
    def _resolve_keys(self) -> ReconConfig:
        left = self.left_group_by or self.left_keys or self.keys
        right = self.right_group_by or self.right_keys
        if not right:
            right = [self.column_mapping.get(k, k) for k in left] if left else []
        if not left and right:
            left = list(right)
        if not left:
            raise ValueError("at least one key column is required (keys=...)")
        if len(left) != len(right):
            raise ValueError(
                f"left keys {left} and right keys {right} must have the same number of columns"
            )
        if len(set(left)) != len(left):
            raise ValueError(f"duplicate key columns: {left}")
        if (self.left_group_by or self.right_group_by) and not self.aggregations:
            raise ValueError("left_group_by/right_group_by require `aggregations`")
        self.left_keys, self.right_keys = list(left), list(right)
        self.keys = list(left)
        for rule in self.rules:
            if rule.column and rule.column in self.keys:
                raise ValueError(f"rule {rule.name!r} targets key column {rule.column!r}")
        return self

    def column_options(self, column: str) -> ColumnOptions:
        opts = self.defaults.merged(self.columns.get(column))
        for rule in self.rules:
            if rule.column == column:
                opts = opts.merged(rule.column_options())
        return opts

    @property
    def resolved_left_keys(self) -> list[str]:
        assert self.left_keys is not None
        return self.left_keys

    @property
    def resolved_right_keys(self) -> list[str]:
        assert self.right_keys is not None
        return self.right_keys
