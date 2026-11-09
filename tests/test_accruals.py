import os
import unittest
from decimal import Decimal

os.environ["LEDGERLY_FAST"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.domain.accruals import VARIANCE_REASONS, AccrualBook, tolerance_for  # noqa: E402
from app.main import app  # noqa: E402

HX = {"HX-Request": "true"}


def settle_all(b: AccrualBook) -> None:
    b.settle("ACR-0901")
    b.settle("ACR-0902")
    b.settle("ACR-0903", VARIANCE_REASONS[0])
    b.release("ACR-0904")


class AccrualBookTest(unittest.TestCase):
    def setUp(self):
        self.b = AccrualBook.new(2026, 10)

    def test_each_opening_accrual_has_a_different_story(self):
        self.assertEqual([self.b.match_status(a.id) for a in self.b.opening], ["exact", "within", "over", "missing"])

    def test_tolerance_has_a_floor(self):
        self.assertEqual(tolerance_for(Decimal("100")), Decimal("25.00"))
        self.assertEqual(tolerance_for(Decimal("2000")), Decimal("100.00"))

    def test_big_difference_needs_a_reason(self):
        with self.assertRaises(ValueError):
            self.b.settle("ACR-0903")
        s = self.b.settle("ACR-0903", VARIANCE_REASONS[1])
        self.assertEqual(s.variance, Decimal("75.00"))

    def test_missing_invoice_cannot_be_settled(self):
        with self.assertRaises(ValueError):
            self.b.settle("ACR-0904")

    def test_carry_forward_reappears_as_a_proposal(self):
        self.b.carry("ACR-0904")
        carried = self.b.proposal("CF-ACR-0904")
        self.assertEqual(carried.amount, Decimal("1800.00"))
        self.assertTrue(self.b.is_included(carried))
        self.b.undo_settlement("ACR-0904")
        self.assertNotIn("CF-ACR-0904", [c.id for c in self.b.proposals()])

    def test_already_invoiced_cost_is_left_out_and_blocks_if_included(self):
        settle_all(self.b)
        self.assertEqual(self.b.blockers(), [])
        self.b.toggle("ACR-1005")
        self.assertTrue(any("book the cost twice" in x for x in self.b.blockers()))

    def test_cannot_book_before_settling(self):
        with self.assertRaises(ValueError):
            self.b.book()

    def test_journal_balances(self):
        settle_all(self.b)
        lines = self.b.book()
        self.assertEqual(sum(j.debit for j in lines), sum(j.credit for j in lines))
        self.assertEqual(lines[-1].account, "2400")

    def test_booking_locks_editing(self):
        settle_all(self.b)
        self.b.book()
        with self.assertRaises(ValueError):
            self.b.set_amount("ACR-1001", Decimal("1"))

    def test_roll_forward_needs_the_stray_entry_fixed(self):
        settle_all(self.b)
        self.b.book()
        rf = self.b.roll_forward()
        self.assertFalse(rf.ties)
        self.assertEqual(rf.difference, Decimal("-86.40"))
        with self.assertRaises(ValueError):
            self.b.sign_off()
        self.b.reclassify_stray()
        self.assertTrue(self.b.roll_forward().ties)
        self.b.sign_off()
        with self.assertRaises(ValueError):
            self.b.unbook()

    def test_pnl_effect(self):
        settle_all(self.b)
        self.b.book()
        expected = self.b.booked_total() + Decimal("36.40") + Decimal("75.00") - Decimal("1800.00")
        self.assertEqual(self.b.pnl_effect(), expected)

    def test_carried_accrual_has_no_net_pnl_effect(self):
        b = AccrualBook.new(2026, 10)
        b.settle("ACR-0901")
        b.settle("ACR-0902")
        b.settle("ACR-0903", VARIANCE_REASONS[0])
        b.carry("ACR-0904")
        b.book()
        self.assertEqual(b.carried_total(), Decimal("1800.00"))
        self.assertEqual(b.pnl_effect(), b.booked_total() - Decimal("1800.00") + Decimal("111.40"))

    def test_manual_accrual_validation(self):
        with self.assertRaises(ValueError):
            self.b.add_manual("Papyrus", "Toner", "1010", Decimal("10"))
        with self.assertRaises(ValueError):
            self.b.add_manual("Papyrus", "Toner", "6400", Decimal("-10"))
        c = self.b.add_manual("Papyrus", "Toner", "6400", Decimal("320"))
        self.assertIn(c, self.b.selected())


class AccrualWebTest(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(app)

    def post(self, url, **data):
        return self.c.post(url, data=data, headers=HX)

    def test_full_close_completes_the_mission(self):
        self.assertEqual(self.c.get("/accruals").status_code, 200)
        self.post("/accruals/settle/ACR-0901")
        self.post("/accruals/settle/ACR-0902")
        self.post("/accruals/settle/ACR-0903", reason=VARIANCE_REASONS[0])
        self.post("/accruals/carry/ACR-0904")
        r = self.post("/accruals/book")
        self.assertIn("Journal posted", r.headers["HX-Trigger"])
        self.post("/accruals/reclassify")
        r = self.post("/accruals/signoff")
        self.assertIn("Signed off", r.text)
        self.assertIn("circle-check", self.c.get("/missions").text)

    def test_bad_input_becomes_a_warning(self):
        r = self.post("/accruals/amount/ACR-1001", amount="abc")
        self.assertIn("doesn't look like an amount", r.headers["HX-Trigger"])
        r = self.post("/accruals/toggle/NOPE")
        self.assertIn("warning", r.headers["HX-Trigger"])

    def test_erp_outage_blocks_booking(self):
        self.post("/sources/erp/toggle")
        r = self.post("/accruals/settle/ACR-0901")
        self.assertIn("offline", r.headers["HX-Trigger"])


if __name__ == "__main__":
    unittest.main()
