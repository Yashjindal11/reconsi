"""Write a demo HTML/Markdown report to reports/ for visual review (reports/ is git-ignored)."""

from __future__ import annotations

from pathlib import Path

from reconsi import reconcile
from reconsi.synthetic import generate_reconciliation_pair

OUT = Path(__file__).resolve().parents[1] / "reports"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    pair = generate_reconciliation_pair(
        rows=20_000,
        missing_rate=0.01,
        extra_rate=0.002,
        mismatch_rate=0.01,
        duplicate_rate=0.002,
        bias=0.025,
        bias_segment=("region", "West"),
        string_format_rate=0.003,
        incident_days=(14, 18),
        seed=7,
    )
    result = reconcile(
        pair.left, pair.right, keys="order_id", duplicate_strategy="first", absolute_tolerance=0.01
    )
    result.to_html(OUT / "preview.html")
    result.to_markdown(OUT / "preview.md")
    print(result)
    print(f"wrote {OUT / 'preview.html'}")


if __name__ == "__main__":
    main()
