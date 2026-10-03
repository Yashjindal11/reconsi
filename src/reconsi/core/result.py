"""The first-class result of a reconciliation run."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from reconsi.comparison.records import STATUS, ColumnStatistics
from reconsi.core.serialization import frame_records, json_dict, to_jsonable
from reconsi.core.types import RecordStatus, Status
from reconsi.keys.analysis import KeyAnalysis
from reconsi.schema.compare import SchemaDiff

if TYPE_CHECKING:
    from reconsi.configuration.models import ReconConfig

RESULT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class RecordMismatch:
    key: dict[str, Any]
    column: str
    left_value: Any
    right_value: Any
    difference: float | None
    relative_difference: float | None
    mismatch_type: str

    def to_dict(self) -> dict[str, Any]:
        return json_dict(
            {
                "key": self.key,
                "column": self.column,
                "left_value": self.left_value,
                "right_value": self.right_value,
                "difference": self.difference,
                "relative_difference": self.relative_difference,
                "mismatch_type": self.mismatch_type,
            }
        )


@dataclass
class ReconciliationResult:
    """Everything ReconSI learned about two datasets.

    Tabular evidence (``value_mismatches``, ``missing_left``, ``missing_right``, ...) is exposed
    as pandas DataFrames; :meth:`to_dict` produces the stable JSON document described in
    ``docs/json-schema.md``.
    """

    config: ReconConfig
    status: Status
    summary: dict[str, Any]
    schema: SchemaDiff
    keys: KeyAnalysis
    columns: dict[str, ColumnStatistics]
    records: pd.DataFrame
    value_mismatches: pd.DataFrame
    missing_left: pd.DataFrame
    """Records present in the right dataset but missing from the left."""
    missing_right: pd.DataFrame
    """Records present in the left dataset but missing from the right."""
    ambiguous: pd.DataFrame
    duplicate_keys: pd.DataFrame
    metadata: dict[str, Any]
    notes: list[dict[str, Any]] = field(default_factory=list)
    analyses: dict[str, Any] = field(default_factory=dict)
    rule_results: list[Any] = field(default_factory=list)
    findings: list[Any] = field(default_factory=list)

    @property
    def key_columns(self) -> list[str]:
        return list(self.keys.keys) + (
            ["_occurrence"] if "_occurrence" in self.records.columns else []
        )

    @property
    def matched(self) -> pd.DataFrame:
        """Keys of records present on both sides with every compared column matching."""
        mask = self.records[STATUS] == RecordStatus.MATCHED.value
        return self.records.loc[mask, self.key_columns].reset_index(drop=True)

    @property
    def mismatched(self) -> pd.DataFrame:
        """Keys of records present on both sides with at least one differing column."""
        mask = self.records[STATUS] == RecordStatus.VALUE_MISMATCH.value
        return self.records.loc[mask, self.key_columns].reset_index(drop=True)

    @property
    def column_statistics(self) -> pd.DataFrame:
        rows = []
        for stats in self.columns.values():
            d = stats.to_dict()
            rows.append(
                {
                    "column": d["column"],
                    "kind": d["kind"],
                    "classification": d["classification"],
                    "compared": d["compared"],
                    "matches": d["matches"],
                    "mismatches": d["mismatches"],
                    "match_percentage": d["match_percentage"],
                    "within_tolerance": d["within_tolerance"],
                    "null_mismatches": d["null_mismatches"],
                    "mean_difference": (d["differences"] or {}).get("mean"),
                    "max_abs_difference": _max_abs(d["differences"]),
                }
            )
        return pd.DataFrame(rows)

    def record_mismatches(self, limit: int | None = None) -> list[RecordMismatch]:
        frame = self.value_mismatches if limit is None else self.value_mismatches.head(limit)
        keys = self.key_columns
        out = []
        for row in frame.to_dict(orient="records"):
            out.append(
                RecordMismatch(
                    key={k: row[k] for k in keys},
                    column=row["column"],
                    left_value=row["left_value"],
                    right_value=row["right_value"],
                    difference=_none_if_nan(row["difference"]),
                    relative_difference=_none_if_nan(row["relative_difference"]),
                    mismatch_type=row["mismatch_type"],
                )
            )
        return out

    # ------------------------------------------------------------------ serialisation
    def to_dict(self, sample_size: int | None = None) -> dict[str, Any]:
        n = self.config.sample_size if sample_size is None else sample_size
        return json_dict(
            {
                "schema_version": RESULT_SCHEMA_VERSION,
                "name": self.config.name,
                "status": self.status,
                "metadata": self.metadata,
                "summary": self.summary,
                "schema": self.schema.to_dict(),
                "keys": self.keys.to_dict(),
                "records": {
                    "missing_left_sample": frame_records(self.missing_left, n),
                    "missing_right_sample": frame_records(self.missing_right, n),
                    "value_mismatch_sample": frame_records(self.value_mismatches, n),
                    "ambiguous_sample": frame_records(self.ambiguous, n),
                    "duplicate_keys_sample": frame_records(self.duplicate_keys, n),
                },
                "columns": {c: s.to_dict() for c, s in self.columns.items()},
                "analyses": self.analyses,
                "rules": [to_jsonable(r) for r in self.rule_results],
                "findings": [to_jsonable(f) for f in self.findings],
                "notes": self.notes,
                "configuration": self.config.model_dump(mode="json", by_alias=True),
            }
        )

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, allow_nan=False)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def __repr__(self) -> str:
        s = self.summary
        return (
            f"<ReconciliationResult {self.status.value}: {s['matched_records']} matched, "
            f"{s['value_mismatch_records']} value mismatches, {s['missing_left']} missing left, "
            f"{s['missing_right']} missing right>"
        )


def _none_if_nan(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _max_abs(diffs: dict[str, Any] | None) -> float | None:
    if not diffs or diffs.get("min") is None:
        return None
    return max(abs(float(diffs["min"])), abs(float(diffs["max"])))
