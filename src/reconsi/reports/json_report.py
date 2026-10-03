"""Machine-readable output: the result JSON document and tabular evidence exports."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from reconsi.core.errors import ReconsiError

if TYPE_CHECKING:
    from reconsi.core.result import ReconciliationResult

SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})

# Top-level keys of the result document and their JSON types (see docs/json-schema.md).
DOCUMENT_FIELDS: dict[str, type | tuple[type, ...]] = {
    "schema_version": str,
    "name": str,
    "status": str,
    "metadata": dict,
    "summary": dict,
    "schema": dict,
    "keys": dict,
    "records": dict,
    "columns": dict,
    "analyses": dict,
    "rules": list,
    "findings": list,
    "recommendations": list,
    "notes": list,
    "configuration": dict,
}
SUMMARY_FIELDS = (
    "left_rows",
    "right_rows",
    "total_records",
    "compared_records",
    "matched_records",
    "value_mismatch_records",
    "missing_left",
    "missing_right",
    "ambiguous_records",
    "match_percentage",
    "mismatch_percentage",
    "missing_percentage",
)
EXPORT_TABLES = (
    "missing_left",
    "missing_right",
    "value_mismatches",
    "ambiguous",
    "duplicate_keys",
    "column_statistics",
    "records",
)
EXPORT_FORMATS = ("csv", "parquet", "json")


def validate_document(doc: Any) -> list[str]:
    """Return a list of problems with a result document (empty when valid)."""
    if not isinstance(doc, dict):
        return ["document must be a JSON object"]
    errors = []
    for key, typ in DOCUMENT_FIELDS.items():
        if key not in doc:
            errors.append(f"missing field {key!r}")
        elif not isinstance(doc[key], typ):
            errors.append(f"field {key!r} has the wrong type")
    if doc.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(f"unsupported schema_version {doc.get('schema_version')!r}")
    if doc.get("status") not in ("PASS", "PASS_WITH_WARNINGS", "FAIL"):
        errors.append("status must be PASS, PASS_WITH_WARNINGS or FAIL")
    summary = doc.get("summary")
    if isinstance(summary, dict):
        errors.extend(f"summary is missing {k!r}" for k in SUMMARY_FIELDS if k not in summary)
    return errors


def load_document(path: str | Path) -> dict[str, Any]:
    """Load and validate a result JSON document written by ReconSI."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconsiError(f"could not read result document {path}: {exc}") from exc
    errors = validate_document(doc)
    if errors:
        raise ReconsiError(f"{path} is not a valid ReconSI result: " + "; ".join(errors))
    assert isinstance(doc, dict)
    return doc


def _table(result: ReconciliationResult, name: str) -> pd.DataFrame:
    if name == "column_statistics":
        return result.column_statistics
    frame = getattr(result, name)
    assert isinstance(frame, pd.DataFrame)
    return frame


def export_evidence(
    result: ReconciliationResult,
    directory: str | Path,
    formats: Iterable[str] = ("csv",),
    tables: Iterable[str] = EXPORT_TABLES,
) -> dict[str, Path]:
    """Write evidence tables (and ``result.json``) into ``directory``. File names are fixed."""
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    fmts = list(formats)
    unknown = [f for f in fmts if f not in EXPORT_FORMATS]
    if unknown:
        raise ReconsiError(f"unsupported export formats {unknown}; choose from {EXPORT_FORMATS}")
    written: dict[str, Path] = {}
    for name in tables:
        if name not in EXPORT_TABLES:
            raise ReconsiError(f"unknown table {name!r}; choose from {EXPORT_TABLES}")
        frame = _table(result, name)
        for fmt in fmts:
            path = out_dir / f"{name}.{fmt}"
            if fmt == "csv":
                frame.to_csv(path, index=False)
            elif fmt == "parquet":
                _object_columns_as_text(frame).to_parquet(path, index=False)
            else:
                frame.to_json(path, orient="records", date_format="iso", indent=1)
            written[f"{name}.{fmt}"] = path
    json_path = out_dir / "result.json"
    result.to_json(json_path)
    written["result.json"] = json_path
    return written


def _object_columns_as_text(frame: pd.DataFrame) -> pd.DataFrame:
    """Parquet needs one type per column; mixed object columns (left/right values) become text."""
    out = frame.copy()
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].map(lambda v: None if v is None or v != v else str(v))
    return out
