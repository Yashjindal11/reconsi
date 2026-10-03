"""Per-column comparison options."""

from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

ColumnKind = Literal["auto", "numeric", "string", "datetime", "boolean"]
StringNormalization = Literal[
    "trim",
    "lowercase",
    "casefold",
    "collapse_whitespace",
    "unicode_nfc",
    "unicode_nfkc",
    "strip_leading_zeros",
]

DEFAULT_FLOAT_RELATIVE_TOLERANCE = 1e-9
"""Applied to float columns when no relative tolerance is configured, so that values that differ
only by binary floating-point representation (``0.1 + 0.2`` vs ``0.3``) are not reported."""


class ColumnOptions(BaseModel):
    """How one column is compared. Every field has a conservative default.

    Numeric values ``a`` and ``b`` match when ``|a - b| <= max(absolute_tolerance,
    relative_tolerance * max(|a|, |b|))`` (the same symmetric rule as :func:`math.isclose`).
    """

    model_config = ConfigDict(extra="forbid")

    type: ColumnKind = "auto"
    absolute_tolerance: float = Field(default=0.0, ge=0)
    relative_tolerance: float | None = Field(default=None, ge=0)
    decimals: int | None = Field(default=None, ge=0, le=15)
    normalize: list[StringNormalization] = Field(default_factory=list)
    timezone: str | None = None
    tolerance_seconds: float = Field(default=0.0, ge=0)
    compare_as_date: bool = False
    null_equals_null: bool = True
    empty_string_as_null: bool = False
    critical: bool = False
    max_mismatch_percentage: float | None = Field(default=None, ge=0, le=100)
    max_mismatches: int | None = Field(default=None, ge=0)

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value

    def merged(self, override: ColumnOptions | None) -> ColumnOptions:
        """Return defaults (self) updated with fields explicitly set on ``override``."""
        if override is None:
            return self
        data = self.model_dump()
        data.update(override.model_dump(exclude_unset=True))
        return ColumnOptions.model_validate(data)
