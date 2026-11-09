import unittest
from decimal import Decimal

from app.domain.generator import GARBLED_STATEMENT, generate_month
from app.domain.posting import SUSPENSE, customer_hint, suggest_account
from app.domain.reconciliation import correcting_entries, reconcile
from app.domain.statement_pdf import parse_statement_pdf, render_statement_pdf


class GeneratorTest(unittest.TestCase):
    def test_same_seed_same_month(self):
        a, b = generate_month(seed=7), generate_month(seed=7)
        self.assertEqual([s.closing for s in a.statements], [s.closing for s in b.statements])

    def test_statements_chain_balances(self):
        m = generate_month()
        for prev, nxt in zip(m.statements, m.statements[1:]):
            self.assertEqual(prev.closing, nxt.opening)

    def test_four_planted_mistakes(self):
        kinds = sorted(e.kind for e in generate_month().errors)
        self.assertEqual(kinds, ["amount", "duplicate", "ledger_only", "timing"])


class PdfRoundTripTest(unittest.TestCase):
    def test_every_normal_statement_parses_exactly(self):
        m = generate_month()
        for st in m.statements:
            if st.number == GARBLED_STATEMENT:
                continue
            p = parse_statement_pdf(render_statement_pdf(st))
            self.assertEqual(p.opening, st.opening, st.code)
            self.assertEqual(p.closing, st.closing, st.code)
            self.assertEqual([l.ref for l in p.lines], [t.ref for t in st.transactions], st.code)
            self.assertEqual(p.gap, 0, st.code)

    def test_garbled_line_is_detected_by_the_balance_check(self):
        st = generate_month().statement(GARBLED_STATEMENT)
        p = parse_statement_pdf(render_statement_pdf(st))
        self.assertEqual(len(p.unreadable), 1)
        self.assertEqual(p.gap, Decimal("-1240.00"))


class PostingRulesTest(unittest.TestCase):
    def test_known_patterns(self):
        self.assertEqual(suggest_account("Payroll October 2026").account, "2100")
        self.assertEqual(suggest_account("Payment from Lumen Labs inv. INV-1").account, "1200")
        self.assertEqual(suggest_account("Card *4417 Metro Fuel").account, "6600")

    def test_unknown_goes_to_suspense_with_a_hint(self):
        s = suggest_account("Incoming transfer from account 4831 2290 ref 1")
        self.assertEqual(s.account, SUSPENSE)
        self.assertFalse(s.confident)
        self.assertIn("Kestrel Media", customer_hint("from account 4831 2290", generate_month().customers))


class ReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.m = generate_month()
        self.posted = self.m.statements[: self.m.initially_posted]
        self.bank = [t for st in self.posted for t in st.transactions]
        self.days = [st.day for st in self.posted]

    def test_classifies_each_planted_mistake(self):
        r = reconcile(self.bank, self.m.ledger_seed, self.m.opening_balance, self.days)
        found = {(i.kind, i.ref) for i in r.problems}
        expected = {(e.kind, e.ref) for e in self.m.errors}
        self.assertEqual(found, expected)
        self.assertEqual(r.unposted, [])

    def test_correcting_entries_make_the_books_agree(self):
        ledger = list(self.m.ledger_seed)
        for issue in reconcile(self.bank, ledger, self.m.opening_balance, self.days).problems:
            ledger += correcting_entries(issue, self.bank, ledger)
        r = reconcile(self.bank, ledger, self.m.opening_balance, self.days)
        self.assertEqual(r.problems, [])
        self.assertTrue(all(d.difference == 0 for d in r.days))


if __name__ == "__main__":
    unittest.main()
