"""Rule-based suggestion of the ledger account for a bank line.

Real finance teams keep a list of "if the description says X, book it to Y" rules.
Lines that no rule recognises go to the suspense account and need a human decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SUSPENSE = "1990"


@dataclass(frozen=True)
class Rule:
    pattern: str
    account: str
    explanation: str


RULES: tuple[Rule, ...] = (
    Rule(r"^Payment from ", "1200", "Customer payment - clears an open invoice"),
    Rule(r"^Transfer to ", "2000", "Supplier payment - settles a purchase invoice"),
    Rule(r"^Payroll ", "2100", "Salaries paid to employees"),
    Rule(r"^VAT payment", "2300", "Tax paid to the tax office"),
    Rule(r"(?i)fee|charge", "6800", "Bank's own fee"),
    Rule(r"^Interest credit", "7100", "Interest earned on the balance"),
    Rule(r"^Card .*(Cloudstack|Byteforge|Printloop)", "6500", "Software subscription"),
    Rule(r"^Card .*(Metro Fuel|Railgo|Cityride)", "6600", "Travel expense"),
    Rule(r"^Card ", "6400", "Small office purchase"),
)


@dataclass(frozen=True)
class Suggestion:
    account: str
    explanation: str
    confident: bool


def suggest_account(description: str) -> Suggestion:
    for rule in RULES:
        if re.search(rule.pattern, description):
            return Suggestion(rule.account, rule.explanation, True)
    return Suggestion(SUSPENSE, "No rule matched - please choose an account", False)


_SENDER = re.compile(r"from account (\d{4} \d{4})")


def customer_hint(description: str, customers: dict[str, str]) -> str | None:
    """For unknown incoming transfers: look the sender's account up in the customer list."""
    m = _SENDER.search(description)
    if m and m.group(1) in customers:
        return f"The sender's account belongs to customer {customers[m.group(1)]} - most likely an invoice payment."
    return None
