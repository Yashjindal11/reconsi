from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from reconsi import reconcile
from reconsi.reports.markdown import render_markdown, table


def _result() -> object:
    rng = np.random.default_rng(0)
    n = 300
    left = pd.DataFrame(
        {
            "id": range(n),
            "date": np.repeat(pd.date_range("2026-09-01", periods=10), n // 10),
            "region": rng.choice(["East", "West|North"], n),
            "revenue": rng.uniform(10, 100, n).round(2),
        }
    )
    right = left.copy()
    right.loc[:40, "revenue"] *= 1.02
    right = right.drop(index=[290, 291])
    return reconcile(left, right, keys="id")


def test_markdown_sections(tmp_path: Path) -> None:
    result = _result()
    text = result.to_markdown(tmp_path / "report.md")  # type: ignore[attr-defined]
    assert (tmp_path / "report.md").read_text() == text
    for heading in (
        "# Reconciliation report",
        "**Status: FAIL**",
        "## Executive summary",
        "## Findings",
        "## Recommendations",
        "## Rules",
        "## Schema differences",
        "## Key analysis",
        "## Column reconciliation",
        "## Numeric differences and systematic bias",
        "## Control totals",
        "## Mismatch concentration",
        "## Temporal analysis",
        "## Value mismatches (sample)",
        "## Missing from right (sample)",
        "## Reproducibility",
    ):
        assert heading in text, heading
    assert "West\\|North" in text  # pipes in data are escaped


def test_table_helper() -> None:
    assert table(["a"], []) == "_None._\n"
    out = table(["a", "b"], [[1234, 0.5], [None, "x|y"]])
    assert "| 1,234 | 0.5 |" in out and "|  | x\\|y |" in out


def test_render_from_document_only() -> None:
    doc = _result().to_dict()  # type: ignore[attr-defined]
    assert render_markdown(doc).startswith("# Reconciliation report")
