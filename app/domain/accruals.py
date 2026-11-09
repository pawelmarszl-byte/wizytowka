"""Month-end accruals: costs the company has incurred but not yet been invoiced for.

The process modelled here is the one most finance teams run every month:

1. **Settle last month's accruals.** They were booked on the last day of the previous month and
   reversed automatically on day 1. When the real invoice arrives it is compared with the estimate:
   a small difference is accepted, a big one needs an explanation, and an accrual with no invoice
   is either carried forward or released.
2. **Book this month's accruals.** Ledgerly proposes them from contracts, recent invoice history and
   anything carried forward. Proposals for costs that are already invoiced are flagged, because
   accruing them would book the cost twice.
3. **Roll forward the accrued expenses account (2400)**, check it agrees with the list of accruals
   and sign off.

Everything is pure Python and deterministic; the web layer only calls these methods.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")
ACCRUALS_ACCOUNT = "2400"
EXPENSE_ACCOUNTS = ("6300", "6400", "6500", "6600", "6700", "6800")

# A settlement difference is accepted without comment up to 5 % of the estimate (at least €25).
TOLERANCE_PCT = Decimal("0.05")
TOLERANCE_MIN = Decimal("25.00")

VARIANCE_REASONS = (
    "Higher usage than estimated",
    "Price increase not in the estimate",
    "Invoice includes extra services",
    "Estimate was wrong",
)


def _d(v: str) -> Decimal:
    return Decimal(v)


@dataclass(frozen=True)
class OpenAccrual:
    """Booked at the end of the previous month, auto-reversed on day 1 of this month."""

    id: str
    supplier: str
    description: str
    account: str
    amount: Decimal
    hint: str = ""


@dataclass(frozen=True)
class Invoice:
    number: str
    supplier: str
    description: str
    account: str
    amount: Decimal
    received: date
    service: str  # service period, e.g. "September"
    accrual_id: str | None = None  # last month's accrual it settles, if any
    note: str = ""


@dataclass(frozen=True)
class Candidate:
    """A proposed accrual for the current month and the evidence behind the amount."""

    id: str
    supplier: str
    description: str
    account: str
    amount: Decimal
    basis: str  # contract | average | annual | carried | manual
    basis_text: str
    history: tuple[tuple[str, Decimal], ...] = ()
    invoiced_by: str | None = None  # invoice number if the cost is already invoiced
    age_days: int = 0


@dataclass(frozen=True)
class Settlement:
    accrual_id: str
    outcome: str  # settled | carried | released
    invoice: str | None = None
    variance: Decimal = ZERO  # invoice minus estimate: extra cost (positive) hitting this month
    reason: str | None = None


@dataclass(frozen=True)
class JournalLine:
    account: str
    debit: Decimal
    credit: Decimal
    text: str


@dataclass(frozen=True)
class StrayEntry:
    """Something booked to the accruals account that doesn't belong there."""

    ref: str
    day: date
    text: str
    amount: Decimal  # effect on the 2400 credit balance (negative = a debit)
    correct_account: str
    why: str


@dataclass(frozen=True)
class RollForward:
    opening: Decimal
    reversed: Decimal
    booked: Decimal
    gl_balance: Decimal
    reclassified: Decimal = ZERO

    @property
    def difference(self) -> Decimal:
        return self.gl_balance - self.closing

    @property
    def closing(self) -> Decimal:
        return self.opening - self.reversed + self.booked

    @property
    def ties(self) -> bool:
        return self.closing == self.gl_balance


def tolerance_for(estimate: Decimal) -> Decimal:
    return max(TOLERANCE_MIN, (abs(estimate) * TOLERANCE_PCT).quantize(CENT, ROUND_HALF_UP))


def average(values) -> Decimal:
    values = list(values)
    return (sum(values, ZERO) / len(values)).quantize(CENT, ROUND_HALF_UP)


# ------------------------------------------------------------------------- the fictional month


def demo_data(year: int, month: int):
    """Last month's open accruals, the invoices received this month and this month's proposals."""
    prev_month = 12 if month == 1 else month - 1
    prev_name = calendar.month_name[prev_month]
    name = calendar.month_name[month]
    d = lambda day: date(year, month, day)  # noqa: E731

    opening = [
        OpenAccrual("ACR-0901", "Quarry & Co Accountants", f"Bookkeeping & payroll services - {prev_name}", "6700",
                    _d("2400.00")),
        OpenAccrual("ACR-0902", "Brightwater Utilities", f"Electricity - {prev_name} (meter estimate)", "6300",
                    _d("1150.00")),
        OpenAccrual("ACR-0903", "Cloudstack Hosting", f"Server usage above plan - {prev_name}", "6500", _d("640.00"),
                    hint="The invoice shows 1.3 TB of extra traffic during a product launch."),
        OpenAccrual("ACR-0904", "Byteforge Software", f"Consulting days - {prev_name}", "6500", _d("1800.00"),
                    hint=f"Byteforge's account manager wrote on 6 {name[:3]}: the consulting days were cancelled "
                         f"and never took place."),
    ]
    invoices = [
        Invoice("QC-2026-1187", "Quarry & Co Accountants", f"Bookkeeping & payroll services - {prev_name}", "6700",
                _d("2400.00"), d(5), prev_name, "ACR-0901"),
        Invoice("BW-884120", "Brightwater Utilities", f"Electricity - {prev_name}", "6300",
                _d("1186.40"), d(8), prev_name, "ACR-0902"),
        Invoice("CS-55-20931", "Cloudstack Hosting", f"Usage above plan - {prev_name}", "6500",
                _d("715.00"), d(9), prev_name, "ACR-0903"),
        Invoice("7731/10", "Greenleaf Cleaning", f"Office cleaning - {name}", "6400",
                _d("1240.00"), d(15), name, None, note="Already paid - it is the line you can repair on statement 014."),
    ]
    utilities = (("Jul", _d("1098.30")), ("Aug", _d("1121.90")), (prev_name[:3], _d("1186.40")))
    usage = (("Jul", _d("602.10")), ("Aug", _d("688.40")), (prev_name[:3], _d("715.00")))
    candidates = [
        Candidate("ACR-1001", "Quarry & Co Accountants", f"Bookkeeping & payroll services - {name}", "6700",
                  _d("2400.00"), "contract", "Fixed monthly fee in the service contract"),
        Candidate("ACR-1002", "Brightwater Utilities", f"Electricity - {name}", "6300", average(v for _, v in utilities),
                  "average", "Average of the last three invoices", utilities),
        Candidate("ACR-1003", "Cloudstack Hosting", f"Server usage above plan - {name}", "6500",
                  average(v for _, v in usage), "average", "Average of the last three invoices", usage),
        Candidate("ACR-1004", "Meridian Audit Partners", f"Year-end audit fee - 1/12 for {name}", "6700",
                  (_d("14400.00") / 12).quantize(CENT), "annual", "Annual fee of €14,400.00 spread evenly over 12 months"),
        Candidate("ACR-1005", "Greenleaf Cleaning", f"Office cleaning - {name}", "6400", _d("1240.00"),
                  "contract", "Fixed monthly fee in the service contract", invoiced_by="7731/10"),
    ]
    stray = StrayEntry("JE-1042", d(14), "Taxi to client meeting - Cityride receipt", _d("-86.40"), "6600",
                       "A travel receipt was booked to the accruals account instead of Travel & fuel (6600).")
    return opening, invoices, candidates, stray


# ------------------------------------------------------------------------- the per-visitor workbook


@dataclass
class AccrualBook:
    year: int
    month: int
    opening: list[OpenAccrual]
    invoices: list[Invoice]
    candidates: list[Candidate]
    stray: StrayEntry | None = None
    stray_fixed: bool = False
    settlements: dict[str, Settlement] = field(default_factory=dict)
    included: dict[str, bool] = field(default_factory=dict)
    amounts: dict[str, Decimal] = field(default_factory=dict)  # user overrides
    manual: list[Candidate] = field(default_factory=list)
    booked: list[Candidate] = field(default_factory=list)
    signed_off: bool = False

    @classmethod
    def new(cls, year: int, month: int) -> "AccrualBook":
        opening, invoices, candidates, stray = demo_data(year, month)
        book = cls(year, month, opening, invoices, candidates, stray)
        book.included = {c.id: c.invoiced_by is None for c in candidates}
        return book

    # ---------------------------------------------------------------- dates

    @property
    def period_end(self) -> date:
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def previous_end(self) -> date:
        return self.first_day - timedelta(days=1)

    @property
    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def reversal_day(self) -> date:
        return self.period_end + timedelta(days=1)

    @property
    def is_booked(self) -> bool:
        return bool(self.booked)

    # ---------------------------------------------------------------- step 1: settle last month

    def accrual(self, accrual_id: str) -> OpenAccrual:
        return next(a for a in self.opening if a.id == accrual_id)

    def invoice(self, number: str) -> Invoice:
        return next(i for i in self.invoices if i.number == number)

    def invoice_for(self, accrual_id: str) -> Invoice | None:
        return next((i for i in self.invoices if i.accrual_id == accrual_id), None)

    def variance(self, accrual_id: str) -> Decimal | None:
        inv = self.invoice_for(accrual_id)
        return None if inv is None else inv.amount - self.accrual(accrual_id).amount

    def match_status(self, accrual_id: str) -> str:
        """exact | within (tolerance) | over (needs a reason) | missing (no invoice yet)."""
        v = self.variance(accrual_id)
        if v is None:
            return "missing"
        if v == ZERO:
            return "exact"
        return "within" if abs(v) <= tolerance_for(self.accrual(accrual_id).amount) else "over"

    @property
    def unresolved(self) -> list[OpenAccrual]:
        return [a for a in self.opening if a.id not in self.settlements]

    def _editable(self) -> None:
        if self.is_booked:
            raise ValueError("This month's accruals are already booked - undo the booking first")

    def settle(self, accrual_id: str, reason: str | None = None) -> Settlement:
        self._editable()
        status = self.match_status(accrual_id)
        if status == "missing":
            raise ValueError("There is no invoice for this accrual yet")
        if status == "over" and reason not in VARIANCE_REASONS:
            raise ValueError("The difference is above tolerance - please give a reason")
        s = Settlement(accrual_id, "settled", self.invoice_for(accrual_id).number, self.variance(accrual_id),
                       reason if status == "over" else None)
        self.settlements[accrual_id] = s
        return s

    def carry(self, accrual_id: str) -> Settlement:
        self._editable()
        if self.match_status(accrual_id) != "missing":
            raise ValueError("This accrual has an invoice - settle it instead")
        s = Settlement(accrual_id, "carried")
        self.settlements[accrual_id] = s
        self.included[f"CF-{accrual_id}"] = True
        return s

    def release(self, accrual_id: str) -> Settlement:
        self._editable()
        if self.match_status(accrual_id) != "missing":
            raise ValueError("This accrual has an invoice - settle it instead")
        s = Settlement(accrual_id, "released", variance=-self.accrual(accrual_id).amount)
        self.settlements[accrual_id] = s
        return s

    def undo_settlement(self, accrual_id: str) -> None:
        self._editable()
        self.settlements.pop(accrual_id, None)
        self.included.pop(f"CF-{accrual_id}", None)
        self.amounts.pop(f"CF-{accrual_id}", None)

    # ---------------------------------------------------------------- step 2: this month's proposals

    def proposals(self) -> list[Candidate]:
        carried = []
        for s in self.settlements.values():
            if s.outcome == "carried":
                a = self.accrual(s.accrual_id)
                carried.append(Candidate(f"CF-{a.id}", a.supplier, f"{a.description} - still not invoiced",
                                         a.account, a.amount, "carried",
                                         f"Carried forward from {self.previous_end:%d %b} ({a.id})",
                                         age_days=(self.period_end - self.previous_end).days))
        return [*self.candidates, *carried, *self.manual]

    def proposal(self, pid: str) -> Candidate:
        return next(c for c in self.proposals() if c.id == pid)

    def amount_of(self, c: Candidate) -> Decimal:
        return self.amounts.get(c.id, c.amount)

    def is_included(self, c: Candidate) -> bool:
        return self.included.get(c.id, True)

    def selected(self) -> list[Candidate]:
        return [c for c in self.proposals() if self.is_included(c)]

    def toggle(self, pid: str) -> bool:
        self._editable()
        c = self.proposal(pid)
        self.included[c.id] = not self.is_included(c)
        return self.included[c.id]

    def set_amount(self, pid: str, amount: Decimal) -> None:
        self._editable()
        if amount <= ZERO:
            raise ValueError("An accrual must be a positive amount")
        c = self.proposal(pid)
        self.amounts[c.id] = amount.quantize(CENT, ROUND_HALF_UP)

    def add_manual(self, supplier: str, description: str, account: str, amount: Decimal) -> Candidate:
        self._editable()
        supplier, description = supplier.strip(), description.strip()
        if not supplier or not description:
            raise ValueError("Please fill in the supplier and what the cost is for")
        if account not in EXPENSE_ACCOUNTS:
            raise ValueError("Please choose an expense account")
        if amount <= ZERO:
            raise ValueError("An accrual must be a positive amount")
        c = Candidate(f"MAN-{len(self.manual) + 1:02d}", supplier[:60], description[:90], account,
                      amount.quantize(CENT, ROUND_HALF_UP), "manual", "Entered by you")
        self.manual.append(c)
        self.included[c.id] = True
        return c

    def remove_manual(self, pid: str) -> None:
        self._editable()
        self.manual = [c for c in self.manual if c.id != pid]
        self.included.pop(pid, None)
        self.amounts.pop(pid, None)

    # ---------------------------------------------------------------- checks and booking

    def blockers(self) -> list[str]:
        out = []
        if self.unresolved:
            n = len(self.unresolved)
            out.append(f"{n} accrual{'s' if n != 1 else ''} from {self.previous_end:%B} still to settle")
        for c in self.selected():
            if c.invoiced_by:
                out.append(f"{c.supplier} is already invoiced ({c.invoiced_by}) - accruing it would book the cost twice")
        if not self.selected():
            out.append("No accruals selected")
        return out

    def journal(self, lines: list[Candidate] | None = None) -> list[JournalLine]:
        lines = self.selected() if lines is None else lines
        out = [JournalLine(c.account, self.amount_of(c), ZERO, f"{c.supplier} - {c.description}") for c in lines]
        total = sum((self.amount_of(c) for c in lines), ZERO)
        if lines:
            out.append(JournalLine(ACCRUALS_ACCOUNT, ZERO, total, f"Accrued expenses {self.period_end:%d %b %Y}"))
        return out

    def book(self) -> list[JournalLine]:
        problems = self.blockers()
        if problems:
            raise ValueError(problems[0])
        self.booked = [Candidate(c.id, c.supplier, c.description, c.account, self.amount_of(c), c.basis,
                                 c.basis_text, c.history, c.invoiced_by, c.age_days) for c in self.selected()]
        return self.journal(self.booked)

    def unbook(self) -> None:
        if self.signed_off:
            raise ValueError("The accruals are signed off and the period is locked")
        self.booked = []

    def sign_off(self) -> None:
        if not self.is_booked:
            raise ValueError("Book this month's accruals first")
        if not self.roll_forward().ties:
            raise ValueError("The 2400 balance in the ledger doesn't agree with the accrual list yet")
        self.signed_off = True

    # ---------------------------------------------------------------- step 3: roll-forward and P&L

    def booked_total(self) -> Decimal:
        return sum((c.amount for c in self.booked), ZERO)

    def planned_total(self) -> Decimal:
        return sum((self.amount_of(c) for c in self.selected()), ZERO)

    def reclassify_stray(self) -> StrayEntry:
        if self.signed_off:
            raise ValueError("The period is locked")
        if self.stray is None or self.stray_fixed:
            raise ValueError("Nothing to reclassify")
        self.stray_fixed = True
        return self.stray

    def gl_entries(self) -> list[tuple[date, str, str, Decimal]]:
        """Account 2400 as the ledger sees it: (day, ref, text, amount); credit balance shown positive."""
        opening = sum((a.amount for a in self.opening), ZERO)
        first = self.previous_end + timedelta(days=1)
        out = [(self.previous_end, "OB", f"Accruals {self.previous_end:%B} (opening balance)", opening),
               (first, "REV", "Automatic reversal of last month's accruals", -opening)]
        if self.stray:
            out.append((self.stray.day, self.stray.ref, self.stray.text, self.stray.amount))
            if self.stray_fixed:
                out.append((self.stray.day, f"{self.stray.ref}-R",
                            f"Reclassified to {self.stray.correct_account}", -self.stray.amount))
        if self.booked:
            out.append((self.period_end, "ACR", f"Accruals {self.period_end:%B}", self.booked_total()))
        return sorted(out, key=lambda e: e[0])

    def roll_forward(self) -> RollForward:
        opening = sum((a.amount for a in self.opening), ZERO)
        gl = sum((e[3] for e in self.gl_entries()), ZERO)
        return RollForward(opening, opening, self.booked_total(), gl)

    def settlement_variance(self) -> Decimal:
        return sum((s.variance for s in self.settlements.values() if s.outcome == "settled"), ZERO)

    def released_total(self) -> Decimal:
        return -sum((s.variance for s in self.settlements.values() if s.outcome == "released"), ZERO)

    def carried_total(self) -> Decimal:
        lines = self.booked if self.booked else self.selected()
        return sum((self.amount_of(c) if not self.booked else c.amount for c in lines if c.basis == "carried"), ZERO)

    def new_accruals_total(self) -> Decimal:
        """This month's accruals excluding carried-forward ones (those were already a cost last month)."""
        total = self.booked_total() if self.booked else self.planned_total()
        return total - self.carried_total()

    def pnl_effect(self) -> Decimal:
        """Net effect of the accrual cycle on this month's expenses.

        Settled: day-1 reversal (credit, estimate) + invoice (debit)  -> the variance.
        Carried: day-1 reversal + re-accrual of the same amount       -> zero.
        Released: day-1 reversal with no invoice                      -> a credit (cost reduction).
        New accruals: debit expense at month end.
        """
        return self.new_accruals_total() + self.settlement_variance() - self.released_total()

    @property
    def step(self) -> int:
        """1 settle, 2 book, 3 sign off, 4 done."""
        if self.signed_off:
            return 4
        if self.is_booked:
            return 3
        return 2 if not self.unresolved else 1
