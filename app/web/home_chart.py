"""The small "bank vs ledger" chart on the home page.

A month of a (fictional) bank balance with the ledger drifting away from it in three places. The server draws
the unreconciled state, so without JS the chart still tells the story; static/js/home-motion.js then draws the
lines in and fixes the mistakes one by one until the difference reaches 0.00, using the numbers below
(embedded as data-* attributes).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

W, H = 560, 300
PAD_L, PAD_R, PAD_T, PAD_B = 48, 14, 16, 30
LO, HI = 44_000.0, 52_000.0

# Daily movements of the bank balance over 22 business days, starting from 47,800.00.
_START = 47_800.0
_MOVES = (0, 1850, -2420, 640, -1180, 2960, -310, -1720, 880, 1410, -2650,
          530, 1980, -860, -1340, 2210, 470, -1590, 920, -2080, 1260, 610)


@dataclass(frozen=True)
class Mistake:
    start: int        # first day the ledger is off
    end: int          # last day it is off (inclusive)
    amount: float     # ledger minus bank while it lasts
    label: str
    at: int           # day the label points at


MISTAKES = (
    Mistake(4, 21, -834.50, "Paid twice", 6),
    Mistake(13, 13, 2000.00, "Booked a day late", 13),
    Mistake(16, 21, -450.00, "Digits swapped", 19),
)


def _bank() -> list[float]:
    out, v = [], _START
    for m in _MOVES:
        v += m
        out.append(round(v, 2))
    return out


def _x(i: int, n: int) -> float:
    return PAD_L + (W - PAD_L - PAD_R) * i / (n - 1)


def _y(v: float) -> float:
    return PAD_T + (H - PAD_T - PAD_B) * (1 - (v - LO) / (HI - LO))


def _path(vals: list[float]) -> str:
    n = len(vals)
    return "M" + " L".join(f"{_x(i, n):.1f} {_y(v):.1f}" for i, v in enumerate(vals))


def home_chart() -> dict:
    bank = _bank()
    n = len(bank)
    ledger = [b + sum(m.amount for m in MISTAKES if m.start <= i <= m.end) for i, b in enumerate(bank)]
    # the gap between the two lines, as one closed shape
    gap = _path(ledger) + " L" + " L".join(f"{_x(i, n):.1f} {_y(bank[i]):.1f}" for i in reversed(range(n))) + " Z"
    marks = []
    for m in MISTAKES:
        mid = m.at
        lx, yb, yl = _x(mid, n), _y(bank[mid]), _y(ledger[mid])
        marks.append({"x": round(lx, 1), "y": round(min(yb, yl) - 16, 1), "py": round((yb + yl) / 2, 1),
                      "top": round(min(yb, yl), 1), "label": m.label})
    grid = [{"y": round(_y(v), 1), "label": f"€{v / 1000:.0f}k"} for v in (44_000, 46_000, 48_000, 50_000, 52_000)]
    return {
        "w": W, "h": H, "bank_d": _path(bank), "ledger_d": _path(ledger), "gap_d": gap, "marks": marks, "grid": grid,
        "x0": PAD_L, "x1": W - PAD_R, "days": [{"x": round(_x(i, n), 1), "label": str(i + 1)} for i in (0, 7, 14, 21)],
        "diff": f"{sum(m.amount for m in MISTAKES if m.end == n - 1):,.2f}",
        "data": json.dumps({
            "bank": bank, "mistakes": [m.__dict__ for m in MISTAKES],
            "w": W, "h": H, "pad": [PAD_L, PAD_R, PAD_T, PAD_B], "lo": LO, "hi": HI,
        }),
    }
