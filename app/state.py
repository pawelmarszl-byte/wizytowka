"""Per-visitor demo state.

Every visitor gets an isolated copy of the demo (keyed by a cookie), so several recruiters can
click around at the same time without seeing each other's changes. State lives in memory only -
on the free hosting tier the disk is ephemeral anyway, and "Reset demo" just drops the session.
"""
from __future__ import annotations

import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from typing import Callable

from .domain.generator import generate_month
from .domain.models import LedgerEntry, MonthData, Statement, Transaction
from .domain.posting import Suggestion, customer_hint, suggest_account
from .domain.reconciliation import Issue, ReconciliationResult, correcting_entries, reconcile
from .domain.statement_pdf import ParsedLine, ParsedStatement, parse_statement_pdf, render_statement_pdf

ARRIVAL_INTERVAL_S = 40
MAX_WAITING = 3  # the bank pauses once this many statements are waiting to be posted
NEW_ARRIVALS = 1  # statements that arrive live during a visit, on top of the ones waiting at the start
OUTAGE_S = 45
SESSION_TTL_S = 3 * 3600
MAX_SESSIONS = 2000

SOURCES = {
    "bank": ("Harbor Bank SFTP", "Where new bank statements come from"),
    "warehouse": ("Data warehouse", "Holds the ledger used by the reconciliation"),
    "erp": ("ERP system", "Receives the postings you approve"),
}


MISSIONS = (
    ("pdf", "Open a bank statement PDF", "Statements → pick any statement → “View original PDF”."),
    ("post", "Post a statement to the ledger", "Statement 013 has a payment no rule recognises - choose an account, then post it."),
    ("repair", "Repair a statement that doesn't add up", "Statement 014 has a line the reader couldn't understand - enter it by hand."),
    ("reconcile", "Find and fix all 4 bookkeeping mistakes", "Reconciliation → run it → use the “Fix” buttons."),
    ("outage", "Survive a connection outage", "Click a dot in the status bar at the bottom and simulate an outage."),
)


class SourceOffline(Exception):
    def __init__(self, source: str):
        self.source = source
        self.name = SOURCES[source][0]
        super().__init__(f"{self.name} is not responding")


@lru_cache(maxsize=1)
def month() -> MonthData:
    return generate_month()


@lru_cache(maxsize=64)
def statement_pdf(number: int) -> bytes:
    return render_statement_pdf(month().statement(number))


@lru_cache(maxsize=64)
def parsed_statement(number: int) -> ParsedStatement:
    return parse_statement_pdf(statement_pdf(number))


@dataclass
class Event:
    at: float
    icon: str
    text: str
    tone: str = "info"  # info | success | warning | danger


@dataclass
class ReviewLine:
    """One line of a statement as Ledgerly presents it for approval."""

    ref: str
    day: object
    description: str
    amount: Decimal
    suggestion: Suggestion
    account: str
    hint: str | None
    manual: bool = False
    chosen: bool = False

    @property
    def needs_decision(self) -> bool:
        """No rule recognised the line and nobody has picked an account yet."""
        return not self.suggestion.confident and not self.chosen


@dataclass
class DemoSession:
    id: str
    clock: Callable[[], float] = time.time
    created: float = 0.0
    last_seen: float = 0.0
    received: int = 0
    next_arrival: float = 0.0
    posted: set[int] = field(default_factory=set)
    ledger: list[LedgerEntry] = field(default_factory=list)
    account_choice: dict[str, str] = field(default_factory=dict)  # ref -> account
    manual_lines: dict[int, list[ParsedLine]] = field(default_factory=dict)
    outages: dict[str, float] = field(default_factory=dict)  # source -> offline until
    events: deque[Event] = field(default_factory=lambda: deque(maxlen=40))
    fixed: dict[str, str] = field(default_factory=dict)  # ref -> issue kind that was fixed
    unseen_arrivals: list[int] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)  # mission progress, see MISSIONS

    def __post_init__(self):
        now = self.clock()
        m = month()
        self.created = self.last_seen = now
        self.received = m.initially_received
        self.next_arrival = now + ARRIVAL_INTERVAL_S
        self.posted = set(range(1, m.initially_posted + 1))
        self.ledger = list(m.ledger_seed)
        # A bit of history so the activity feed isn't empty on arrival.
        history = [
            (5400, "upload", "ERP import: statements 001-012 booked by the accounting team"),
            (3000, "pencil", "Manual entry MAN-0007 (cash deposit) added by a team member"),
            (900, "file-down", f"Statements {m.statement(13).code} - {m.statement(m.initially_received).code} received, waiting to be posted"),
        ]
        for ago, icon, text in history:
            self.events.appendleft(Event(now - ago, icon, text))
        self.log("rocket", "You joined the demo - all data for " + m.label + " is fictional")

    # ------------------------------------------------------------------ basics

    def log(self, icon: str, text: str, tone: str = "info") -> None:
        self.events.appendleft(Event(self.clock(), icon, text, tone))

    def is_online(self, source: str) -> bool:
        return self.outages.get(source, 0) <= self.clock()

    def offline_for(self, source: str) -> int:
        return max(0, int(self.outages.get(source, 0) - self.clock()))

    def require(self, source: str) -> None:
        if not self.is_online(source):
            raise SourceOffline(source)

    def simulate_outage(self, source: str) -> None:
        self.outages[source] = self.clock() + OUTAGE_S
        self.flags.add("outage")
        self.log("plug-zap", f"{SOURCES[source][0]} went offline (simulated)", "danger")

    def restore(self, source: str) -> None:
        self.outages.pop(source, None)
        self.log("plug", f"{SOURCES[source][0]} is back online", "success")

    def missions(self) -> list[dict]:
        return [dict(key=k, title=t, hint=h, done=k in self.flags) for k, t, h in MISSIONS]

    # ------------------------------------------------------------------ statements

    @property
    def statements(self) -> list[Statement]:
        return month().statements[: self.received]

    @property
    def total_statements(self) -> int:
        m = month()
        return min(len(m.statements), m.initially_received + NEW_ARRIVALS)

    @property
    def waiting(self) -> int:
        """Received statements not yet posted."""
        return self.received - len(self.posted)

    @property
    def inbox_full(self) -> bool:
        return self.waiting >= MAX_WAITING

    def tick(self) -> list[int]:
        """Called on every request: let statements 'arrive' while the bank is online."""
        now = self.clock()
        self.last_seen = now
        if self.inbox_full:
            # Paused: the countdown restarts once the user posts something.
            self.next_arrival = max(self.next_arrival, now + ARRIVAL_INTERVAL_S)
            return []
        if self.received >= self.total_statements or now < self.next_arrival:
            return []
        if not self.is_online("bank"):
            self.next_arrival = self.outages["bank"] + 5
            return []
        # At most one per request, so a visitor returning after a break sees them trickle in.
        self.next_arrival = now + ARRIVAL_INTERVAL_S
        return [self._receive()]

    def fetch_now(self) -> int | None:
        """'Check for new statements' button: fetch the next one immediately."""
        self.require("bank")
        if self.received >= self.total_statements or self.inbox_full:
            return None
        number = self._receive()
        self.next_arrival = self.clock() + ARRIVAL_INTERVAL_S
        return number

    def _receive(self) -> int:
        self.received += 1
        st = month().statement(self.received)
        self.unseen_arrivals.append(self.received)
        self.log("file-down", f"Statement {st.code} received from Harbor Bank ({len(st.transactions)} lines)")
        return self.received

    def pop_arrivals(self) -> list[Statement]:
        out = [month().statement(n) for n in self.unseen_arrivals]
        self.unseen_arrivals.clear()
        return out

    def parsed(self, number: int) -> ParsedStatement:
        base = parsed_statement(number)
        extra = self.manual_lines.get(number, [])
        if not extra:
            return base
        readable_refs = {l.ref for l in extra}
        return ParsedStatement(base.statement_date, base.opening, base.closing,
                               [*base.lines, *extra],
                               [u for u in base.unreadable if not any(r in u for r in readable_refs)])

    def review_lines(self, number: int) -> list[ReviewLine]:
        customers = month().customers
        manual_refs = {l.ref for l in self.manual_lines.get(number, [])}
        out = []
        for line in self.parsed(number).lines:
            s = suggest_account(line.description)
            out.append(ReviewLine(line.ref, line.day, line.description, line.amount, s,
                                  self.account_choice.get(line.ref, s.account),
                                  None if s.confident else customer_hint(line.description, customers),
                                  line.ref in manual_refs, line.ref in self.account_choice))
        return out

    def status(self, number: int) -> str:
        """posted | blocked (doesn't add up) | review (needs a decision) | ready."""
        if number in self.posted:
            return "posted"
        p = self.parsed(number)
        if p.gap != 0 or p.unreadable:
            return "blocked"
        if any(l.needs_decision for l in self.review_lines(number)):
            return "review"
        return "ready"

    def choose_account(self, ref: str, account: str) -> None:
        self.account_choice[ref] = account

    def add_manual_line(self, number: int, raw: str, ref: str, description: str, amount: Decimal) -> None:
        st = month().statement(number)
        self.manual_lines.setdefault(number, []).append(ParsedLine(st.day, ref, description, amount))
        ok = self.parsed(number).gap == 0
        if ok:
            self.flags.add("repair")
        tone = "success" if ok else "warning"
        self.log("pencil", f"Line {ref} on statement {st.code} entered manually ({amount:,.2f})", tone)

    def clear_manual_lines(self, number: int) -> None:
        self.manual_lines.pop(number, None)

    def post(self, number: int) -> int:
        self.require("erp")
        status = self.status(number)
        if status == "blocked":
            raise ValueError("This statement does not add up yet")
        if status == "review":
            raise ValueError("Some lines still need an account")
        st = month().statement(number)
        lines = self.review_lines(number)
        for l in lines:
            self.ledger.append(LedgerEntry(l.day, l.account, l.amount, l.ref, l.description, "Ledgerly"))
        self.posted.add(number)
        self.flags.add("post")
        self.ledger.sort(key=lambda e: e.day)
        self.log("check-circle", f"Statement {st.code} posted to the ledger ({len(lines)} entries)", "success")
        return len(lines)

    def unpost(self, number: int) -> None:
        self.require("erp")
        st = month().statement(number)
        refs = {t.ref for t in st.transactions} | {l.ref for l in self.manual_lines.get(number, [])}
        self.ledger = [e for e in self.ledger if not (e.source == "Ledgerly" and e.ref in refs)]
        self.posted.discard(number)
        self.log("undo-2", f"Posting of statement {st.code} reversed", "warning")

    # ------------------------------------------------------------------ reconciliation

    @property
    def bank_feed(self) -> list[Transaction]:
        return [t for st in self.statements for t in st.transactions]

    def reconciliation(self) -> ReconciliationResult:
        self.require("warehouse")
        return reconcile(self.bank_feed, self.ledger, month().opening_balance,
                         [st.day for st in self.statements])

    def fix(self, ref: str) -> Issue | None:
        self.require("erp")
        result = self.reconciliation()
        issue = next((i for i in result.problems if i.ref == ref), None)
        if issue is None:
            return None
        self.ledger.extend(correcting_entries(issue, self.bank_feed, self.ledger))
        self.ledger.sort(key=lambda e: e.day)
        self.fixed[ref] = issue.kind
        if not self.reconciliation().problems:
            self.flags.add("reconcile")
        self.log("wrench", f"Fixed: {issue.title.lower()} ({ref})", "success")
        return issue


class SessionStore:
    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self._sessions: dict[str, DemoSession] = {}

    def get(self, sid: str | None) -> tuple[DemoSession, bool]:
        """Return (session, created_new)."""
        self._purge()
        if sid and sid in self._sessions:
            return self._sessions[sid], False
        return self.new(), True

    def new(self) -> DemoSession:
        sid = secrets.token_urlsafe(18)
        session = DemoSession(sid, clock=self.clock)
        self._sessions[sid] = session
        return session

    def reset(self, sid: str | None) -> DemoSession:
        if sid:
            self._sessions.pop(sid, None)
        return self.new()

    def _purge(self) -> None:
        now = self.clock()
        stale = [k for k, s in self._sessions.items() if now - s.last_seen > SESSION_TTL_S]
        for k in stale:
            del self._sessions[k]
        if len(self._sessions) > MAX_SESSIONS:
            for k in sorted(self._sessions, key=lambda k: self._sessions[k].last_seen)[: len(self._sessions) - MAX_SESSIONS]:
                del self._sessions[k]

    def __len__(self) -> int:
        return len(self._sessions)
