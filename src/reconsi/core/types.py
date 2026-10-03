"""Shared enumerations used across ReconSI."""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    """Overall reconciliation outcome. See ``docs/rules.md`` for the exact definition."""

    PASS = "PASS"  # noqa: S105
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"  # noqa: S105
    FAIL = "FAIL"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Evidence(StrEnum):
    """How strongly a finding is supported. ReconSI never presents a guess as a fact."""

    OBSERVED = "observed"
    STATISTICAL = "statistically_supported"
    LIKELY = "likely_explanation"
    RULE = "user_configured_rule"


class MismatchType(StrEnum):
    NUMERIC = "numeric"
    STRING = "string"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    NULL = "null"
    DATATYPE = "datatype"


class RecordStatus(StrEnum):
    MATCHED = "matched"
    VALUE_MISMATCH = "value_mismatch"
    MISSING_LEFT = "missing_left"
    """Present in the right dataset, missing from the left dataset."""
    MISSING_RIGHT = "missing_right"
    """Present in the left dataset, missing from the right dataset."""
    AMBIGUOUS = "ambiguous"
    """Key is duplicated and the ``strict`` strategy refused to guess a pairing."""


class DuplicateStrategy(StrEnum):
    STRICT = "strict"
    FIRST = "first"
    LAST = "last"
    AGGREGATE = "aggregate"
    MULTISET = "multiset"
    GROUPED = "grouped"
