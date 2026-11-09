"""Core domain objects: bank statements, transactions and ledger accounts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

CURRENCY = "EUR"
BANK_ACCOUNT = "1010"

CHART_OF_ACCOUNTS: dict[str, str] = {
    "1010": "Cash at bank - Harbor Bank",
    "1200": "Accounts receivable",
    "1990": "Suspense account",
    "2000": "Accounts payable",
    "2100": "Wages payable",
    "2300": "VAT payable",
    "2400": "Accrued expenses",
    "6300": "Utilities",
    "6400": "Office supplies",
    "6500": "Software & IT services",
    "6600": "Travel & fuel",
    "6700": "Professional fees",
    "6800": "Bank charges",
    "7100": "Interest income",
    "7200": "Other income",
}

# Accounts a user may pick for a bank line (everything except the bank account itself).
POSTABLE_ACCOUNTS = {k: v for k, v in CHART_OF_ACCOUNTS.items() if k != BANK_ACCOUNT}


@dataclass(frozen=True)
class Transaction:
    ref: str
    day: date
    description: str
    amount: Decimal  # positive = money in, negative = money out
    kind: str  # generator category, e.g. "customer_receipt"; "unknown" = needs review


@dataclass(frozen=True)
class Statement:
    number: int  # 1-based sequence within the month
    day: date
    opening: Decimal
    transactions: tuple[Transaction, ...]
    garbled_ref: str | None = None  # line printed in a format the parser can't read

    @property
    def closing(self) -> Decimal:
        return self.opening + sum((t.amount for t in self.transactions), Decimal("0"))

    @property
    def code(self) -> str:
        return f"{self.day:%Y/%m}/{self.number:03d}"

    @property
    def net(self) -> Decimal:
        return self.closing - self.opening


@dataclass(frozen=True)
class InjectedError:
    """A deliberate mistake planted in the ledger so the reconciliation has something to find."""

    kind: str  # duplicate | amount | timing | ledger_only
    ref: str
    note: str


@dataclass(frozen=True)
class LedgerEntry:
    day: date
    counter: str  # the other side of the entry (the bank account 1010 is always one side)
    amount: Decimal  # impact on the bank account: positive = debit (money in)
    ref: str
    description: str
    source: str  # "ERP import", "Manual entry", "Ledgerly", "Correction", "Opening balance"


@dataclass
class MonthData:
    year: int
    month: int
    opening_balance: Decimal
    statements: list[Statement]
    ledger_seed: list[LedgerEntry]  # what the accounting team had already booked
    errors: list[InjectedError]
    initially_received: int
    initially_posted: int
    customers: dict[str, str] = field(default_factory=dict)  # bank account id -> customer name

    @property
    def label(self) -> str:
        return date(self.year, self.month, 1).strftime("%B %Y")

    def statement(self, number: int) -> Statement:
        return self.statements[number - 1]
