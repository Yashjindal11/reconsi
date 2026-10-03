from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd

from reconsi import reconcile
from reconsi.reports.html import SECTIONS, render_html
from reconsi.visualization import svg

XSS = "<script>alert(1)</script>"


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts = 0
        self.external: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if tag == "script":
            self.scripts += 1
            if d.get("src"):
                self.external.append(str(d["src"]))
        if tag == "link" and d.get("href"):
            self.external.append(str(d["href"]))
        if d.get("id"):
            self.ids.add(str(d["id"]))


def _result() -> object:
    rng = np.random.default_rng(0)
    n = 400
    left = pd.DataFrame(
        {
            "id": range(n),
            "date": np.repeat(pd.date_range("2026-09-01", periods=10), n // 10),
            "region": rng.choice(["East", "West", XSS], n),
            "revenue": rng.uniform(10, 100, n).round(2),
            "name": "acme",
        }
    )
    right = left.copy()
    right.loc[:60, "revenue"] *= 1.02
    right.loc[300:310, "name"] = " ACME"
    right = right.drop(index=[390, 391, 392])
    return reconcile(left, right, keys="id")


def test_html_report_is_standalone_and_complete(tmp_path: Path) -> None:
    result = _result()
    html = result.to_html(tmp_path / "r.html")  # type: ignore[attr-defined]
    assert (tmp_path / "r.html").read_text() == html
    parser = _Collector()
    parser.feed(html)
    assert parser.scripts == 1 and parser.external == []
    assert {sid for sid, _ in SECTIONS} <= parser.ids
    assert "http://" not in html.replace("http://www.w3.org", "") and "https://" not in html
    assert html.count("<svg") >= 4


def test_html_escapes_data() -> None:
    html = _result().to_html()  # type: ignore[attr-defined]
    assert XSS not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_render_from_document_and_empty_sections() -> None:
    frame = pd.DataFrame({"id": [1, 2], "v": [1, 2]})
    doc = reconcile(frame, frame, keys="id").to_dict()
    html = render_html(doc)
    assert "Pass</span>" in html
    assert "No date column was found" in html


def test_svg_helpers_escape_and_handle_edge_cases() -> None:
    assert svg.hbar([]) == ""
    out = svg.hbar([("<b>", 1.0)], title="<t>")
    assert "&lt;b&gt;" in out and "<b>" not in out
    assert svg.histogram([], []) == ""
    assert "<polyline" in svg.line(["a"], [50.0])
    assert re.search(r"<rect", svg.stacked([("a", 0, "#000"), ("b", 1, "#fff")]))
