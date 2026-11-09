"""Bank-to-ledger reconciliation.

For every transaction reference we compare *what the bank says* (date -> amount) with
*what the ledger says* (date -> amount, after netting corrections). If the two maps are
equal the item is matched; otherwise the shape of the difference tells us what went wrong.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .models import LedgerEntry, Transaction

ZERO = Decimal("0")

KIND_TITLES = {
    "duplicate": "Booked twice",
    "amount": "Wrong amount",
    "timing": "Booked on the wrong day",
    "ledger_only": "Missing from the bank",
    "unposted": "Not posted yet",
}


@dataclass(frozen=True)
class Issue:
    kind: str
    ref: str
    description: str
    bank_amount: Decimal
    ledger_amount: Decimal
    bank_day: date | None
    ledger_day: date | None
    counter: str

    @property
    def title(self) -> str:
        return KIND_TITLES[self.kind]

    @property
    def difference(self) -> Decimal:
        """Ledger minus bank - what the ledger has too much (positive) or too little."""
        return self.ledger_amount - self.bank_amount

    @property
    def fixable(self) -> bool:
        return self.kind != "unposted"

    @property
    def explanation(self) -> str:
        d = abs(self.difference)
        match self.kind:
            case "duplicate":
                return (f"The bank paid this once, but the ledger shows it twice. "
                        f"The books overstate this movement by €{d:,.2f}.")
            case "amount":
                return (f"The bank shows €{abs(self.bank_amount):,.2f}, the ledger €{abs(self.ledger_amount):,.2f}. "
                        f"Looks like a typing mistake - two digits swapped.")
            case "timing":
                return (f"The amount is right, but it was booked on {self.ledger_day:%d %b} instead of "
                        f"{self.bank_day:%d %b}. Daily balances are off for one day.")
            case "ledger_only":
                return (f"Someone booked €{d:,.2f} into the bank account, but the money never "
                        f"arrived. It should be reversed or investigated.")
            case _:
                return "The bank statement has arrived, but nobody has posted it to the ledger yet."

    @property
    def fix_label(self) -> str:
        return {
            "duplicate": "Remove the duplicate",
            "amount": "Correct the amount",
            "timing": "Move to the bank date",
            "ledger_only": "Reverse the entry",
        }.get(self.kind, "Go to statements")


@dataclass(frozen=True)
class DayBalance:
    day: date
    bank: Decimal
    ledger: Decimal

    @property
    def difference(self) -> Decimal:
        return self.ledger - self.bank


@dataclass(frozen=True)
class ReconciliationResult:
    issues: list[Issue]
    days: list[DayBalance]
    matched: int
    bank_lines: int
    ledger_lines: int

    @property
    def problems(self) -> list[Issue]:
        return [i for i in self.issues if i.kind != "unposted"]

    @property
    def unposted(self) -> list[Issue]:
        return [i for i in self.issues if i.kind == "unposted"]

    @property
    def closing_difference(self) -> Decimal:
        return self.days[-1].difference if self.days else ZERO

    @property
    def problem_total(self) -> Decimal:
        return sum((abs(i.difference) for i in self.problems), ZERO)


def _by_day(items) -> dict[date, Decimal]:
    out: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for day, amount in items:
        out[day] += amount
    return {d: a for d, a in out.items() if a != ZERO}


def reconcile(bank: list[Transaction], ledger: list[LedgerEntry], opening: Decimal,
              bank_days: list[date]) -> ReconciliationResult:
    bank_by_ref: dict[str, list[Transaction]] = defaultdict(list)
    for t in bank:
        bank_by_ref[t.ref].append(t)
    ledger_by_ref: dict[str, list[LedgerEntry]] = defaultdict(list)
    for e in ledger:
        ledger_by_ref[e.ref].append(e)

    issues: list[Issue] = []
    matched = 0
    for ref in list(dict.fromkeys([*bank_by_ref, *ledger_by_ref])):
        b_items, l_items = bank_by_ref.get(ref, []), ledger_by_ref.get(ref, [])
        b_map = _by_day((t.day, t.amount) for t in b_items)
        l_map = _by_day((e.day, e.amount) for e in l_items)
        if b_map == l_map:
            matched += 1
            continue

        b_total, l_total = sum(b_map.values(), ZERO), sum(l_map.values(), ZERO)
        originals = [e for e in l_items if e.source != "Correction"]
        if not b_map:
            kind = "ledger_only"
        elif not l_map:
            kind = "unposted"
        elif b_total == l_total:
            kind = "timing"
        elif len(originals) > 1 and l_total == b_total * len(originals):
            kind = "duplicate"
        else:
            kind = "amount"

        source = b_items[0] if b_items else l_items[0]
        issues.append(Issue(
            kind=kind,
            ref=ref,
            description=source.description,
            bank_amount=b_total,
            ledger_amount=l_total,
            bank_day=min(b_map) if b_map else None,
            ledger_day=min(l_map) if l_map else None,
            counter=l_items[0].counter if l_items else "",
        ))

    order = ["duplicate", "amount", "timing", "ledger_only", "unposted"]
    issues.sort(key=lambda i: (order.index(i.kind), i.bank_day or i.ledger_day or date.min))

    days = []
    bank_daily = _by_day((t.day, t.amount) for t in bank)
    ledger_daily = _by_day((e.day, e.amount) for e in ledger)
    bank_bal = ledger_bal = opening
    for d in bank_days:
        bank_bal += bank_daily.get(d, ZERO)
        ledger_bal += ledger_daily.get(d, ZERO)
        days.append(DayBalance(d, bank_bal, ledger_bal))

    return ReconciliationResult(issues, days, matched, len(bank), len(ledger))


def correcting_entries(issue: Issue, bank: list[Transaction], ledger: list[LedgerEntry]) -> list[LedgerEntry]:
    """Entries that turn the ledger's picture of one reference into the bank's picture."""
    b_map = _by_day((t.day, t.amount) for t in bank if t.ref == issue.ref)
    l_map = _by_day((e.day, e.amount) for e in ledger if e.ref == issue.ref)
    out = []
    for day in sorted(set(b_map) | set(l_map)):
        diff = b_map.get(day, ZERO) - l_map.get(day, ZERO)
        if diff != ZERO:
            out.append(LedgerEntry(day, issue.counter or "1990", diff, issue.ref,
                                   f"Correction: {issue.title.lower()} - {issue.description}", "Correction"))
    return out
