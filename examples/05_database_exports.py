"""Example 5: two Parquet exports of the same table from different database snapshots.

The second export has a new column, a dropped column, a timezone bug in `updated_at` for some
rows and a handful of changed statuses. Run through a YAML job, with history and evidence export.
"""

from __future__ import annotations

from _common import out_dir

from reconsi import Reconciliation, load_config
from reconsi.synthetic import generate_reconciliation_pair

JOB = """
name: orders_export_check
left: {path: export_monday.parquet}
right: {path: export_tuesday.parquet}
keys: [order_id]
exclude_columns: [discount]
columns:
  revenue: {absolute_tolerance: 0.01}
thresholds:
  max_missing_records: 0
  max_mismatch_percentage: 0.5
  max_schema_changes: 2
history: {path: history.db}
"""


def main() -> None:
    out = out_dir("05_database_exports")
    pair = generate_reconciliation_pair(
        20_000, timestamp_shift_rate=0.004, mismatch_rate=0.001, schema_changes=True, seed=5
    )
    pair.left.to_parquet(out / "export_monday.parquet", index=False)
    pair.right.to_parquet(out / "export_tuesday.parquet", index=False)
    (out / "job.yaml").write_text(JOB)

    config = load_config(out / "job.yaml")
    result = Reconciliation(config=config, base_dir=out).run()
    print(result)
    print("added:", result.schema.added, "removed:", result.schema.removed)
    for s in result.schema.suggestions:
        print(f"suggestion: {s.left} <-> {s.right}")
    for hint in result.columns["updated_at"].hints:
        print("updated_at hint:", hint["kind"], hint.get("offset") or hint.get("precision") or "")
    files = result.export(out / "evidence", formats=["csv", "parquet"])
    print(f"exported {len(files)} files to {out / 'evidence'}")


if __name__ == "__main__":
    main()
