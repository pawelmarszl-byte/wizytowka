"""Server-rendered SVG chart: bank balance vs ledger balance, plus the daily difference.

Rendering on the server keeps the front-end free of chart libraries - HTMX just swaps the
SVG in. Two stacked panels share the x-axis; each has its own single y-axis (no dual axes).
Hover behaviour (crosshair + tooltip) lives in static/js/app.js and reads data-* attributes.
"""
from __future__ import annotations

from decimal import Decimal
from html import escape

from ..domain.reconciliation import DayBalance

W, H_TOP, H_BOT, GAP, X_AXIS = 1040, 300, 130, 40, 28
PAD_L, PAD_R, PAD_T, PAD_B = 64, 16, 14, 26


def _nice_step(span: float, ticks: int = 4) -> float:
    raw = span / ticks
    mag = 10 ** len(str(int(raw))) / 10 if raw >= 1 else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _k(v: float) -> str:
    if abs(v) >= 1000:
        return f"€{v / 1000:,.0f}k"
    return f"€{v:,.0f}"


def balance_chart(days: list[DayBalance], highlight: str | None = None) -> str:
    if not days:
        return ""
    n = len(days)
    plot_w = W - PAD_L - PAD_R
    xs = [PAD_L + plot_w * (i + 0.5) / n for i in range(n)]

    vals = [float(v) for d in days for v in (d.bank, d.ledger)]
    lo, hi = min(vals), max(vals)
    step = _nice_step(hi - lo or 1)
    lo = (lo // step) * step
    hi = (hi // step + 1) * step

    def y_top(v: float) -> float:
        return PAD_T + (H_TOP - PAD_T - PAD_B) * (1 - (v - lo) / (hi - lo))

    diffs = [float(d.difference) for d in days]
    dmax = max(1.0, max(abs(v) for v in diffs))
    dstep = _nice_step(dmax, 2)
    dmax = (dmax // dstep + 1) * dstep
    bot0 = H_TOP + GAP
    mid = bot0 + (H_BOT - 18) / 2

    def y_bot(v: float) -> float:
        return mid - (H_BOT - 18) / 2 * (v / dmax)

    total_h = H_TOP + GAP + H_BOT + X_AXIS
    out = [f'<svg class="chart" viewBox="0 0 {W} {total_h}" role="img" '
           f'aria-label="Daily bank balance compared with ledger balance" data-chart>']

    # Grid + y labels (top panel).
    v = lo
    while v <= hi + 1e-6:
        y = y_top(v)
        out.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="axis" x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end">{_k(v)}</text>')
        v += step

    # Bottom panel: zero line, scale, bars.
    out.append(f'<text class="panel-title" x="{PAD_L}" y="{bot0 - 6}">Difference (ledger − bank)</text>')
    for v in (dmax, 0, -dmax):
        y = y_bot(v)
        out.append(f'<line class="{"zero" if v == 0 else "grid"}" x1="{PAD_L}" x2="{W - PAD_R}" '
                   f'y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="axis" x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end">'
                   f'{"€0" if v == 0 else _k(v)}</text>')
    bar_w = max(4.0, min(18.0, plot_w / n - 6))
    for x, d in zip(xs, diffs):
        if abs(d) < 0.005:
            continue
        y0, y1 = sorted((y_bot(0), y_bot(d)))
        h = max(2.0, y1 - y0)
        cls = "bar-pos" if d > 0 else "bar-neg"
        out.append(f'<rect class="{cls}" x="{x - bar_w / 2:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" '
                   f'height="{h:.1f}" rx="2"/>')

    # X labels: every few days.
    every = max(1, n // 8)
    for i, (x, d) in enumerate(zip(xs, days)):
        if i % every == 0 or i == n - 1:
            out.append(f'<text class="axis" x="{x:.1f}" y="{total_h - 8}" text-anchor="middle">'
                       f'{d.day:%d %b}</text>')

    # Lines: ledger under bank so a perfect match shows the bank line on top.
    def path(key: str) -> str:
        pts = [f"{x:.1f},{y_top(float(getattr(d, key))):.1f}" for x, d in zip(xs, days)]
        return "M" + " L".join(pts)

    out.append(f'<path class="line-ledger" d="{path("ledger")}"/>')
    out.append(f'<path class="line-bank" d="{path("bank")}"/>')

    # Markers on days with a difference, crosshair, and hover hit areas.
    for x, d in zip(xs, days):
        if d.difference != 0:
            out.append(f'<circle class="dot-ledger" cx="{x:.1f}" cy="{y_top(float(d.ledger)):.1f}" r="4"/>')
    out.append(f'<line class="crosshair" x1="0" x2="0" y1="{PAD_T}" y2="{bot0 + H_BOT - 18}" data-crosshair/>')
    slot = plot_w / n
    for x, d in zip(xs, days):
        hl = " hl" if highlight and d.day.isoformat() == highlight else ""
        out.append(
            f'<rect class="hit{hl}" x="{x - slot / 2:.1f}" y="{PAD_T}" width="{slot:.1f}" '
            f'height="{bot0 + H_BOT - 18 - PAD_T}" tabindex="0" data-x="{x:.1f}" '
            f'data-day="{d.day:%a %d %b}" data-bank="{_money(d.bank)}" data-ledger="{_money(d.ledger)}" '
            f'data-diff="{_money(d.difference, signed=True)}" data-ok="{int(d.difference == 0)}"/>')
    out.append("</svg>")
    return "".join(out)


def _money(v: Decimal, signed: bool = False) -> str:
    sign = "+" if signed and v > 0 else ("−" if v < 0 else "")
    return escape(f"{sign}€{abs(v):,.2f}")
