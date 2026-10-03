"""Dependency-free inline SVG charts for the standalone HTML report."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

INK = "#1d1d1b"
MUTED = "#6b6b66"
RULE = "#e4e1d8"
OK = "#2f6b3a"
WARN = "#a86b00"
BAD = "#a12a2a"
NEUTRAL = "#5b6f86"
FONT = "font-family:inherit;font-size:12px"


def _fmt(v: float) -> str:
    if abs(v) >= 1000 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.3g}"


def hbar(
    rows: Sequence[tuple[str, float]],
    *,
    color: str = NEUTRAL,
    width: int = 640,
    value_format: str = "number",
    max_value: float | None = None,
    title: str = "",
) -> str:
    """Horizontal bar chart. ``value_format`` is ``number`` or ``percent`` (values 0-100)."""
    if not rows:
        return ""
    label_w, value_w, bar_h, gap = 170, 70, 16, 6
    plot_w = width - label_w - value_w
    top = max(max_value or 0.0, max(v for _, v in rows), 1e-12)
    height = len(rows) * (bar_h + gap) + gap
    parts = [
        f'<svg class="chart" role="img" aria-label="{escape(title)}" viewBox="0 0 {width} {height}" '
        f'width="100%" style="max-width:{width}px">'
    ]
    for i, (label, value) in enumerate(rows):
        y = gap + i * (bar_h + gap)
        w = max(0.0, plot_w * value / top)
        shown = f"{value:.2f}%" if value_format == "percent" else _fmt(value)
        short = label if len(label) <= 26 else label[:25] + "..."
        parts.append(
            f'<text x="{label_w - 8}" y="{y + 12}" text-anchor="end" fill="{INK}" style="{FONT}">'
            f"<title>{escape(label)}</title>{escape(short)}</text>"
            f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="{bar_h}" fill="{color}"/>'
            f'<text x="{label_w + w + 6:.1f}" y="{y + 12}" fill="{MUTED}" style="{FONT}">{escape(shown)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def stacked(
    segments: Sequence[tuple[str, float, str]], *, width: int = 640, title: str = ""
) -> str:
    """A single 100% stacked bar followed by an HTML legend (which wraps on narrow screens)."""
    total = sum(v for _, v, _ in segments) or 1.0
    parts = [
        f'<svg class="chart" role="img" aria-label="{escape(title)}" viewBox="0 0 {width} 22" '
        f'width="100%" style="max-width:{width}px;margin-bottom:.3rem">'
    ]
    x = 0.0
    for label, value, color in segments:
        w = width * value / total
        if w > 0:
            parts.append(
                f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="22" fill="{color}">'
                f"<title>{escape(label)}: {_fmt(value)}</title></rect>"
            )
        x += w
    parts.append('</svg><div class="legend">')
    for label, value, color in segments:
        text = f"{label} {_fmt(value)} ({100 * value / total:.1f}%)"
        parts.append(f'<span><i style="background:{color}"></i>{escape(text)}</span>')
    parts.append("</div>")
    return "".join(parts)


def histogram(
    counts: Sequence[float], edges: Sequence[float], *, width: int = 640, title: str = ""
) -> str:
    if not counts:
        return ""
    height, pad_l, pad_b = 150, 8, 30
    plot_w, plot_h = width - 2 * pad_l, height - pad_b - 6
    top = max(counts) or 1.0
    bw = plot_w / len(counts)
    parts = [
        f'<svg class="chart" role="img" aria-label="{escape(title)}" viewBox="0 0 {width} {height}" '
        f'width="100%" style="max-width:{width}px">'
    ]
    zero_x = None
    for i, c in enumerate(counts):
        h = plot_h * c / top
        x = pad_l + i * bw
        lo, hi = edges[i], edges[i + 1]
        color = BAD if hi <= 0 else (OK if lo >= 0 else NEUTRAL)
        parts.append(
            f'<rect x="{x:.1f}" y="{6 + plot_h - h:.1f}" width="{max(bw - 1, 1):.1f}" height="{h:.1f}" '
            f'fill="{color}"><title>{_fmt(lo)} to {_fmt(hi)}: {int(c)}</title></rect>'
        )
        if lo <= 0 <= hi and edges[0] < 0 < edges[-1]:
            zero_x = x + bw * (0 - lo) / (hi - lo if hi != lo else 1)
    parts.append(
        f'<line x1="{pad_l}" y1="{6 + plot_h}" x2="{width - pad_l}" y2="{6 + plot_h}" stroke="{RULE}"/>'
        f'<text x="{pad_l}" y="{height - 10}" fill="{MUTED}" style="{FONT}">{escape(_fmt(edges[0]))}</text>'
        f'<text x="{width - pad_l}" y="{height - 10}" text-anchor="end" fill="{MUTED}" style="{FONT}">'
        f"{escape(_fmt(edges[-1]))}</text>"
    )
    if zero_x is not None:
        parts.append(
            f'<line x1="{zero_x:.1f}" y1="6" x2="{zero_x:.1f}" y2="{6 + plot_h}" stroke="{INK}" '
            f'stroke-dasharray="3,3"/><text x="{zero_x:.1f}" y="{height - 10}" text-anchor="middle" '
            f'fill="{INK}" style="{FONT}">0</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def line(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    markers: Sequence[int] = (),
    highlights: Sequence[int] = (),
    width: int = 720,
    y_label: str = "",
    title: str = "",
) -> str:
    """Line chart of a percentage series with optional change-point markers."""
    if not values:
        return ""
    height, pad_l, pad_r, pad_t, pad_b = 200, 48, 12, 12, 36
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    lo, hi = lo - 0.05 * span, hi + 0.05 * span
    n = len(values)

    def xy(i: int, v: float) -> tuple[float, float]:
        x = pad_l + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)
        return x, pad_t + plot_h * (1 - (v - lo) / (hi - lo))

    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(i, v) for i, v in enumerate(values)))
    parts = [
        f'<svg class="chart" role="img" aria-label="{escape(title)}" viewBox="0 0 {width} {height}" '
        f'width="100%" style="max-width:{width}px">',
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" y2="{pad_t + plot_h}" stroke="{RULE}"/>',
        f'<text x="{pad_l - 6}" y="{pad_t + 10}" text-anchor="end" fill="{MUTED}" style="{FONT}">{hi:.1f}</text>',
        f'<text x="{pad_l - 6}" y="{pad_t + plot_h}" text-anchor="end" fill="{MUTED}" style="{FONT}">{lo:.1f}</text>',
        f'<text x="4" y="{pad_t + plot_h / 2}" fill="{MUTED}" style="{FONT}" transform="rotate(-90 10 {pad_t + plot_h / 2})">{escape(y_label)}</text>',
    ]
    for i in markers:
        if 0 <= i < n:
            x, _ = xy(i, values[i])
            parts.append(
                f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t + plot_h}" stroke="{WARN}" '
                f'stroke-dasharray="4,3"><title>change point: {escape(labels[i])}</title></line>'
            )
    parts.append(f'<polyline points="{pts}" fill="none" stroke="{INK}" stroke-width="1.5"/>')
    for i, v in enumerate(values):
        x, y = xy(i, v)
        color = BAD if i in highlights else INK
        r = 3.5 if i in highlights else 2
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}"><title>{escape(labels[i])}: '
            f"{v:.2f}</title></circle>"
        )
    for i in sorted({0, n // 2, n - 1}):
        x, _ = xy(i, values[i])
        parts.append(
            f'<text x="{x:.1f}" y="{height - 12}" text-anchor="middle" fill="{MUTED}" style="{FONT}">'
            f"{escape(labels[i])}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)
