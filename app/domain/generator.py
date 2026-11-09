"""Deterministic generator of one month of fictional banking data.

Everything here is invented: the bank, the companies, the amounts. The same seed always
produces the same month, so tests and screenshots are reproducible.

The month is split into three groups of daily statements:
  * already received and already posted to the ledger by the "accounting team"
    (this part contains the planted mistakes the reconciliation should catch),
  * received but still waiting to be posted (the user posts them in the Statements module),
  * not yet received - they "arrive" one by one while the user is clicking around.
"""
from __future__ import annotations

import calendar
import random
from datetime import date, timedelta
from decimal import Decimal

from .models import InjectedError, LedgerEntry, MonthData, Statement, Transaction
from .posting import suggest_account

CENT = Decimal("0.01")

CUSTOMERS = {
    "4831 2290": "Kestrel Media",
    "5520 1187": "Bluefin Logistics",
    "6604 9921": "Oakridge Dental Clinic",
    "3390 4410": "Pinecone Studio",
    "7781 3305": "Arcadia Foods",
    "2290 6712": "Silverline Motors",
    "9014 2276": "Harborview Hotels",
    "1187 5530": "Lumen Labs",
}
SUPPLIERS = [
    "Papyrus Office Supply",
    "Greenleaf Cleaning",
    "Vantage Property Rentals",
    "Cloudstack Hosting",
    "Byteforge Software",
    "Quarry & Co Accountants",
]
CARD_MERCHANTS = [
    ("Cloudstack", 19, 89),
    ("Byteforge", 12, 49),
    ("Printloop", 9, 35),
    ("Metro Fuel", 40, 120),
    ("Railgo", 25, 210),
    ("Cityride", 8, 32),
    ("Corner Stationers", 6, 60),
    ("Bean There Cafe", 7, 45),
]

# Statement numbers (1-based) that drive the story.
POSTED_UNTIL = 12  # statements 1..12 were booked by the team
RECEIVED_UNTIL = 15  # statements 13..15 are waiting for the user; 16.. arrive live
GARBLED_STATEMENT = 14  # contains a line the PDF parser cannot read


def _money(rng: random.Random, low: float, high: float) -> Decimal:
    return Decimal(str(rng.uniform(low, high))).quantize(CENT)


def _business_days(year: int, month: int) -> list[date]:
    days = calendar.monthrange(year, month)[1]
    return [d for i in range(1, days + 1) if (d := date(year, month, i)).weekday() < 5]


def _transpose(amount: Decimal) -> Decimal:
    """Swap two neighbouring digits - the classic typing mistake (1,240.00 -> 1,420.00)."""
    digits = list(f"{amount:.2f}")
    for i in range(len(digits) - 4):
        a, b = digits[i], digits[i + 1]
        if a.isdigit() and b.isdigit() and a != b:
            digits[i], digits[i + 1] = b, a
            return Decimal("".join(digits))
    return amount + Decimal("90.00")


def generate_month(year: int = 2026, month: int = 10, seed: int = 42) -> MonthData:
    rng = random.Random(seed)
    days = _business_days(year, month)
    ref_counter = iter(range(30_000_000, 99_999_999, 7_919))
    invoice_counter = iter(range(400, 9_999))

    def ref() -> str:
        return f"HB{next(ref_counter)}"

    def tx(day: date, description: str, amount: Decimal, kind: str) -> Transaction:
        return Transaction(ref(), day, description, amount.quantize(CENT), kind)

    customer_names = list(CUSTOMERS.values())
    statements: list[Statement] = []
    balance = Decimal("184250.37")
    opening_balance = balance

    for number, day in enumerate(days, start=1):
        lines: list[Transaction] = []
        for _ in range(rng.randint(1, 4)):
            name = rng.choice(customer_names)
            lines.append(tx(day, f"Payment from {name} inv. INV-{year}-{next(invoice_counter):04d}",
                            _money(rng, 650, 12_500), "customer_receipt"))
        for _ in range(rng.randint(0, 2)):
            supplier = rng.choice(SUPPLIERS)
            lines.append(tx(day, f"Transfer to {supplier} inv. {rng.randint(1000, 9999)}/{month:02d}",
                            -_money(rng, 280, 6_200), "supplier_payment"))
        for _ in range(rng.randint(0, 3)):
            merchant, low, high = rng.choice(CARD_MERCHANTS)
            lines.append(tx(day, f"Card *4417 {merchant}", -_money(rng, low, high), "card_payment"))

        # Fixed monthly events.
        if number == len(days) - 3:
            lines.append(tx(day, f"VAT payment {date(year, month - 1 or 12, 1):%B}", Decimal("-13420.55"), "tax"))
        if number == len(days) - 2:
            lines.append(tx(day, f"Payroll {date(year, month, 1):%B %Y}", Decimal("-48600.00"), "payroll"))
        if number == len(days):
            lines.append(tx(day, "Monthly account fee", Decimal("-38.50"), "bank_fee"))
            lines.append(tx(day, "Interest credit", Decimal("61.20"), "interest"))

        # Lines no posting rule recognises - the user has to decide.
        if number == 13:
            lines.append(tx(day, "Incoming transfer from account 4831 2290 ref 88213",
                            Decimal("3175.00"), "unknown"))
        if number == 15:
            lines.append(tx(day, "Refund REF-55102", Decimal("142.80"), "unknown"))
        if number == 18:
            lines.append(tx(day, "Incoming transfer from account 7712 0045", Decimal("250.00"), "unknown"))

        garbled = None
        if number == GARBLED_STATEMENT:
            line = tx(day, "Transfer to Greenleaf Cleaning inv. 7731/10", Decimal("-1240.00"), "supplier_payment")
            lines.append(line)
            garbled = line.ref

        rng.shuffle(lines)
        statement = Statement(number, day, balance, tuple(lines), garbled)
        statements.append(statement)
        balance = statement.closing

    ledger, errors = _seed_ledger(statements, days, rng)
    return MonthData(
        year=year,
        month=month,
        opening_balance=opening_balance,
        statements=statements,
        ledger_seed=ledger,
        errors=errors,
        initially_received=RECEIVED_UNTIL,
        initially_posted=POSTED_UNTIL,
        customers=dict(CUSTOMERS),
    )


def _seed_ledger(statements: list[Statement], days: list[date], rng: random.Random):
    """Book statements 1..POSTED_UNTIL the way a busy team would - including four mistakes."""
    entries: list[LedgerEntry] = []
    posted = statements[:POSTED_UNTIL]
    for st in posted:
        for t in st.transactions:
            entries.append(LedgerEntry(t.day, suggest_account(t.description).account, t.amount,
                                       t.ref, t.description, "ERP import"))

    def pick(statement_no: int, kind: str) -> Transaction:
        return next(t for t in statements[statement_no - 1].transactions if t.kind == kind)

    errors: list[InjectedError] = []

    # 1. Duplicate: the same supplier payment imported twice.
    dup = next(t for st in posted[2:] for t in st.transactions if t.kind == "supplier_payment")
    original = next(e for e in entries if e.ref == dup.ref)
    entries.insert(entries.index(original) + 1, original)
    errors.append(InjectedError("duplicate", dup.ref, "Supplier payment imported twice"))

    # 2. Wrong amount: two digits swapped while typing a customer receipt by hand.
    wrong = pick(7, "customer_receipt")
    i = next(i for i, e in enumerate(entries) if e.ref == wrong.ref)
    e = entries[i]
    entries[i] = LedgerEntry(e.day, e.counter, _transpose(e.amount), e.ref, e.description, "Manual entry")
    errors.append(InjectedError("amount", wrong.ref, "Digits swapped when typing the amount"))

    # 3. Timing: a card payment booked one business day late.
    late = next(t for st in posted[8:] for t in st.transactions if t.kind == "card_payment")
    i = next(i for i, e in enumerate(entries) if e.ref == late.ref)
    e = entries[i]
    next_day = days[days.index(e.day) + 1]
    entries[i] = LedgerEntry(next_day, e.counter, e.amount, e.ref, e.description, "Manual entry")
    errors.append(InjectedError("timing", late.ref, "Booked one day after the bank date"))

    # 4. Ledger only: a cash deposit someone booked but never took to the bank.
    day = statements[9].day
    entries.append(LedgerEntry(day, "7200", Decimal("500.00"), "MAN-0007",
                               "Cash deposit - petty cash", "Manual entry"))
    errors.append(InjectedError("ledger_only", "MAN-0007", "Booked in the ledger, never reached the bank"))

    entries.sort(key=lambda e: e.day)
    return entries, errors


def statement_due_offsets(month: MonthData, interval_s: int) -> dict[int, int]:
    """Seconds after a session starts at which each not-yet-received statement arrives."""
    late = range(month.initially_received + 1, len(month.statements) + 1)
    return {n: (i + 1) * interval_s for i, n in enumerate(late)}


def previous_business_day(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d
