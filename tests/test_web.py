import os
import unittest

os.environ["LEDGERLY_FAST"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, store  # noqa: E402
from app.state import month  # noqa: E402

HX = {"HX-Request": "true"}


def unknown_ref(number: int) -> str:
    return next(t.ref for t in month().statement(number).transactions if t.kind == "unknown")


class WebFlowTest(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(app)

    def test_pages_render(self):
        home = self.c.get("/")
        self.assertIn("Paweł Marszałek", home.text)
        self.assertIn('href="/demo"', home.text)
        for url in ("/demo", "/statements", "/reconciliation", "/about"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertIn("Ledgerly", r.text)

    def test_sessions_are_isolated(self):
        other = TestClient(app)
        self.c.get("/demo")
        other.get("/demo")
        self.assertNotEqual(self.c.cookies.get("ledgerly_session"), other.cookies.get("ledgerly_session"))

    def test_pdf_download(self):
        r = self.c.get("/statements/1/pdf")
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertEqual(self.c.get("/statements/99/pdf").status_code, 404)

    def test_post_needs_a_decision_first(self):
        r = self.c.post("/statements/13/post", headers=HX)
        self.assertIn("still need an account", r.headers["HX-Trigger"])
        self.c.post("/statements/13/account", data={"ref": unknown_ref(13), "account": "1200"}, headers=HX)
        r = self.c.post("/statements/13/post", headers=HX)
        self.assertIn("statements-changed", r.headers["HX-Trigger"])
        self.assertIn("Posted to the ledger", r.text)

    def test_blocked_statement_repair(self):
        r = self.c.get("/statements/14", headers=HX)
        self.assertIn("numbers don't add up", r.text)
        raw = next(u for u in month().statement(14).transactions if u.ref == month().statement(14).garbled_ref)
        line = f"261020 {raw.ref} {raw.description} 1 240,00 DR 0.00"
        wrong = self.c.post("/statements/14/repair", data={"raw": line, "amount": "1420", "direction": "out"}, headers=HX)
        self.assertIn("Still doesn", wrong.headers["HX-Trigger"])
        ok = self.c.post("/statements/14/repair", data={"raw": line, "amount": "1240.00", "direction": "out"}, headers=HX)
        self.assertIn("adds up", ok.text)
        self.assertIn("statement adds up", ok.text)

    def test_fixing_all_mistakes(self):
        for err in month().errors:
            self.c.post(f"/reconciliation/fix/{err.ref}", headers=HX)
        r = self.c.get("/reconciliation/run", headers=HX)
        self.assertIn("No bookkeeping mistakes left", r.text)

    def test_outage_and_reconnect(self):
        self.c.post("/sources/warehouse/toggle", headers=HX)
        self.assertIn("not responding", self.c.get("/reconciliation/run", headers=HX).text)
        self.c.post("/sources/warehouse/toggle", headers=HX)
        self.assertIn("Matched", self.c.get("/reconciliation/run", headers=HX).text)

    def test_reset_starts_over(self):
        self.c.post("/sources/erp/toggle", headers=HX)
        before = self.c.cookies.get("ledgerly_session")
        r = self.c.post("/reset")
        self.assertEqual(r.headers["HX-Redirect"], "/demo")
        self.assertNotEqual(before, self.c.cookies.get("ledgerly_session"))

    def _session(self):
        self.c.get("/demo")
        return store.get(self.c.cookies.get("ledgerly_session"))[0]

    def test_at_most_three_statements_wait(self):
        s = self._session()
        self.assertEqual(s.waiting, 3)
        s.next_arrival = 0  # pretend the interval has passed
        self.c.get("/statements/list", headers=HX)
        r = self.c.post("/statements/fetch", headers=HX)
        self.assertEqual(s.waiting, 3)
        self.assertIn("post one to receive the next", r.headers["HX-Trigger"])

    def test_posting_lets_the_next_statement_arrive(self):
        s = self._session()
        start = s.received
        self.c.post("/statements/13/account", data={"ref": unknown_ref(13), "account": "1200"}, headers=HX)
        self.c.post("/statements/13/post", headers=HX)
        s.next_arrival = 0
        self.c.get("/statements/list", headers=HX)
        self.assertEqual(s.received, start + 1)
        self.assertEqual(s.waiting, 3)

    def test_only_one_new_statement_arrives(self):
        s = self._session()
        start = s.received
        for _ in range(3):
            s.posted.add(s.received)  # free the inbox, then let time pass
            s.next_arrival = 0
            self.c.get("/statements/list", headers=HX)
        self.assertEqual(s.received, start + 1)
        self.assertEqual(s.received, s.total_statements)


if __name__ == "__main__":
    unittest.main()
