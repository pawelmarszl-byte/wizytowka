"""Ledgerly - FastAPI + HTMX demo app.

Routes return full pages for normal navigation and HTML fragments for HTMX requests.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .domain.accruals import EXPENSE_ACCOUNTS, VARIANCE_REASONS
from .domain.models import CHART_OF_ACCOUNTS, POSTABLE_ACCOUNTS
from .domain.reconciliation import KIND_TITLES
from .state import SOURCES, DemoSession, SessionStore, SourceOffline, month, statement_pdf
from .web.chart import balance_chart

BASE = Path(__file__).parent
COOKIE = "ledgerly_session"
# Simulated network latency; set LEDGERLY_FAST=1 (tests) to skip it.
FAST = os.environ.get("LEDGERLY_FAST") == "1"

GITHUB_URL = "https://github.com/pawelmarszl-byte/wizytowka"


class CachedStatic(StaticFiles):
    """Static files: cached for a year when the URL carries a ?v= fingerprint (see asset()), revalidated otherwise."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        versioned = b"v=" in scope.get("query_string", b"")
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if versioned else "no-cache"
        return resp


app = FastAPI(title="Ledgerly", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=800)
app.mount("/static", CachedStatic(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def asset(path: str) -> str:
    """URL of a static file with its modification time as a fingerprint, so it can be cached for a long time."""
    try:
        v = int((BASE / "static" / path).stat().st_mtime)
    except OSError:
        v = 0
    return f"/static/{path}?v={v}"


def site_url(request: Request) -> str:
    """Public address of the site (SITE_URL if set, otherwise taken from the request) - no trailing slash."""
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"].rstrip("/")
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    return f"{scheme}://{request.url.netloc}"


templates.env.globals.update(asset=asset, GITHUB_URL=GITHUB_URL)
store = SessionStore()


def money(v, signed: bool = False) -> str:
    v = Decimal(v)
    sign = "+" if signed and v > 0 else ("−" if v < 0 else "")
    return f"{sign}€{abs(v):,.2f}"


templates.env.filters["money"] = money
templates.env.globals.update(ACCOUNTS=CHART_OF_ACCOUNTS, POSTABLE=POSTABLE_ACCOUNTS, SOURCES=SOURCES,
                             KIND_TITLES=KIND_TITLES, EXPENSE_ACCOUNTS=EXPENSE_ACCOUNTS,
                             VARIANCE_REASONS=VARIANCE_REASONS)


async def latency(low: float = 0.35, high: float = 0.9) -> None:
    if not FAST:
        await asyncio.sleep(random.uniform(low, high))


def session_of(request: Request) -> tuple[DemoSession, bool]:
    s, new = store.get(request.cookies.get(COOKIE))
    s.tick()
    return s, new


def render(request: Request, template: str, s: DemoSession, new: bool = False, http_status: int = 200,
           toast: tuple[str, str] | None = None, events: tuple[str, ...] = (), **ctx) -> HTMLResponse:
    ctx.update(request=request, s=s, m=month(), is_htmx="HX-Request" in request.headers)
    resp = templates.TemplateResponse(request, template, ctx, status_code=http_status)
    trigger: dict = {e: True for e in events}
    if toast:
        trigger["toast"] = {"tone": toast[0], "text": toast[1]}
    if trigger:
        resp.headers["HX-Trigger"] = json.dumps(trigger)
    if new:
        resp.set_cookie(COOKIE, s.id, httponly=True, samesite="lax", max_age=3 * 3600)
    return resp


def offline(request: Request, s: DemoSession, err: SourceOffline, new: bool = False) -> HTMLResponse:
    return render(request, "partials/offline.html", s, new, err=err)


# ------------------------------------------------------------------------- pages


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Personal landing page; the demo lives under /demo."""
    return templates.TemplateResponse(request, "home.html", {"site": site_url(request)})


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots(request: Request):
    return "\n".join(["User-agent: *", "Allow: /", f"Sitemap: {site_url(request)}/sitemap.xml", ""])


@app.get("/sitemap.xml")
async def sitemap(request: Request):
    site = site_url(request)
    urls = "".join(f"<url><loc>{site}{path}</loc></url>" for path in ("/", "/demo", "/about"))
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, media_type="application/xml")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(asset("img/logo.svg"), status_code=301)


@app.get("/demo", response_class=HTMLResponse)
async def dashboard(request: Request):
    s, new = session_of(request)
    try:
        rec = s.reconciliation()
    except SourceOffline:
        rec = None
    counts = {k: 0 for k in ("posted", "ready", "review", "blocked")}
    for st in s.statements:
        counts[s.status(st.number)] += 1
    return render(request, "dashboard.html", s, new, page="dashboard", rec=rec, counts=counts)


@app.get("/statements", response_class=HTMLResponse)
async def statements(request: Request, open: int | None = None):
    s, new = session_of(request)
    if open is None:
        open = next((st.number for st in s.statements if s.status(st.number) != "posted"), s.received)
    return render(request, "statements.html", s, new, page="statements", selected=open)


@app.get("/statements/list", response_class=HTMLResponse)
async def statement_list(request: Request, selected: int | None = None):
    s, new = session_of(request)
    arrived = s.pop_arrivals()
    toast = None
    if arrived:
        toast = ("info", f"New statement {arrived[-1].code} arrived from Harbor Bank")
    return render(request, "partials/statement_list.html", s, new, toast=toast, selected=selected)


@app.post("/statements/fetch", response_class=HTMLResponse)
async def fetch(request: Request):
    s, new = session_of(request)
    await latency(0.8, 1.6)
    try:
        number = s.fetch_now()
    except SourceOffline as e:
        return render(request, "partials/statement_list.html", s, new, selected=None, toast=("danger", f"{e.name} is not responding - try again in a moment"))
    s.pop_arrivals()
    if number:
        toast = ("info", f"Statement {month().statement(number).code} downloaded")
    elif s.inbox_full:
        toast = ("warning", f"{s.waiting} statements are already waiting - post one to receive the next")
    else:
        toast = ("info", "No new statements - that was the last one in this demo")
    return render(request, "partials/statement_list.html", s, new, selected=number, toast=toast)


def _detail(request: Request, s: DemoSession, number: int, new=False, toast=None, events=(), **extra):
    if not 1 <= number <= s.received:
        return render(request, "partials/empty.html", s, new, http_status=404)
    st = month().statement(number)
    return render(request, "partials/statement_detail.html", s, new, toast=toast, events=events, st=st,
                  parsed=s.parsed(number), lines=s.review_lines(number), status=s.status(number), **extra)


@app.get("/statements/{number}", response_class=HTMLResponse)
async def statement_detail(request: Request, number: int):
    s, new = session_of(request)
    if not request.headers.get("HX-Request"):
        return RedirectResponse(f"/statements?open={number}")
    await latency(0.2, 0.5)
    return _detail(request, s, number, new)


@app.get("/statements/{number}/pdf")
async def statement_pdf_file(request: Request, number: int, download: int = 0):
    s, _ = session_of(request)
    if not 1 <= number <= s.received:
        return Response(status_code=404)
    s.flags.add("pdf")
    st = month().statement(number)
    name = f"harbor-bank-statement-{st.code.replace('/', '-')}.pdf"
    disposition = "attachment" if download else "inline"
    return Response(statement_pdf(number), media_type="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="{name}"'})


@app.post("/statements/{number}/account", response_class=HTMLResponse)
async def choose_account(request: Request, number: int, ref: str = Form(...), account: str = Form(...)):
    s, new = session_of(request)
    if account in POSTABLE_ACCOUNTS:
        s.choose_account(ref, account)
    return _detail(request, s, number, new)


_LEGACY = re.compile(r"(HB\d+)\s+(.+?)\s+([\d ]+,\d{2})\s+(DR|CR)\b")


@app.post("/statements/{number}/repair", response_class=HTMLResponse)
async def repair(request: Request, number: int, raw: str = Form(...), amount: str = Form(...),
                 direction: str = Form(...)):
    s, new = session_of(request)
    m = _LEGACY.search(raw)
    try:
        value = Decimal(amount.replace(",", "").replace("€", "").strip())
    except InvalidOperation:
        return _detail(request, s, number, new, toast=("danger", "That doesn't look like an amount"))
    if not m or value <= 0:
        return _detail(request, s, number, new, toast=("danger", "Please enter a positive amount"))
    signed = -value if direction == "out" else value
    s.add_manual_line(number, raw, m.group(1), m.group(2), signed)
    ok = s.parsed(number).gap == 0
    toast = ("success", "Statement now adds up - ready to post") if ok else \
        ("warning", "Still doesn't add up - check the amount against the PDF")
    if not ok:
        s.clear_manual_lines(number)
    return _detail(request, s, number, new, toast=toast, repair_failed=not ok)


@app.post("/statements/{number}/post", response_class=HTMLResponse)
async def post(request: Request, number: int):
    s, new = session_of(request)
    await latency(0.6, 1.2)
    try:
        n = s.post(number)
    except SourceOffline as e:
        return _detail(request, s, number, new, toast=("danger", f"{e.name} is offline - posting failed"))
    except ValueError as e:
        return _detail(request, s, number, new, toast=("warning", str(e)))
    return _detail(request, s, number, new, toast=("success", f"{n} entries sent to the ledger"),
                   events=("statements-changed",))


@app.post("/statements/{number}/unpost", response_class=HTMLResponse)
async def unpost(request: Request, number: int):
    s, new = session_of(request)
    try:
        s.unpost(number)
    except SourceOffline as e:
        return _detail(request, s, number, new, toast=("danger", f"{e.name} is offline"))
    return _detail(request, s, number, new, toast=("warning", "Posting reversed"),
                   events=("statements-changed",))


@app.get("/reconciliation", response_class=HTMLResponse)
async def reconciliation_page(request: Request):
    s, new = session_of(request)
    return render(request, "reconciliation.html", s, new, page="reconciliation")


@app.get("/reconciliation/run", response_class=HTMLResponse)
async def reconciliation_run(request: Request, focus: str | None = None, steps: int = 0):
    """With steps=1 the client shows a staged progress bar; this endpoint does the real work."""
    s, new = session_of(request)
    await latency(0.9, 1.6) if steps else await latency(0.1, 0.25)
    try:
        rec = s.reconciliation()
    except SourceOffline as e:
        return offline(request, s, e, new)
    return render(request, "partials/reconciliation_result.html", s, new, rec=rec, focus=focus,
                  chart=balance_chart(rec.days))


@app.post("/reconciliation/fix/{ref}", response_class=HTMLResponse)
async def reconciliation_fix(request: Request, ref: str):
    s, new = session_of(request)
    await latency(0.4, 0.8)
    try:
        issue = s.fix(ref)
        rec = s.reconciliation()
    except SourceOffline as e:
        return offline(request, s, e, new)
    toast = ("success", f"Correction posted: {issue.fix_label.lower()}") if issue else None
    if issue and not rec.problems:
        toast = ("success", "All bookkeeping mistakes fixed - the books agree with the bank")
    return render(request, "partials/reconciliation_result.html", s, new, rec=rec, focus=None,
                  chart=balance_chart(rec.days), toast=toast, just_fixed=ref)


# ------------------------------------------------------------------------- accruals


def _accruals(request: Request, s: DemoSession, new=False, toast=None, **extra):
    return render(request, "partials/accruals_body.html", s, new, toast=toast, b=s.accruals,
                  events=("refresh-missions",), **extra)


def _amount(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "").replace("€", "").replace(" ", "").strip())
    except InvalidOperation:
        return None


@app.get("/accruals", response_class=HTMLResponse)
async def accruals_page(request: Request):
    s, new = session_of(request)
    return render(request, "accruals.html", s, new, page="accruals", b=s.accruals)


async def _accrual_action(request: Request, action, success: str | None, delay=(0.2, 0.5), **extra):
    """Run one state change and re-render the workbook; domain errors become warning toasts."""
    s, new = session_of(request)
    await latency(*delay)
    try:
        result = action(s)
    except SourceOffline as e:
        return _accruals(request, s, new, toast=("danger", f"{e.name} is offline - nothing was booked"), **extra)
    except (ValueError, StopIteration) as e:
        msg = str(e) if isinstance(e, ValueError) else "That item doesn't exist"
        return _accruals(request, s, new, toast=("warning", msg), **extra)
    text = success(result) if callable(success) else success
    return _accruals(request, s, new, toast=("success", text) if text else None, **extra)


@app.post("/accruals/settle/{accrual_id}", response_class=HTMLResponse)
async def accrual_settle(request: Request, accrual_id: str, reason: str = Form("")):
    return await _accrual_action(
        request, lambda s: s.settle_accrual(accrual_id, reason or None),
        lambda st: f"Settled with invoice {st.invoice}" + (f" - {money(st.variance, True)} to this month's P&L" if st.variance else ""),
        flash=accrual_id)


@app.post("/accruals/carry/{accrual_id}", response_class=HTMLResponse)
async def accrual_carry(request: Request, accrual_id: str):
    return await _accrual_action(request, lambda s: s.carry_accrual(accrual_id),
                                 "Carried forward - it now appears in this month's proposals", flash=accrual_id)


@app.post("/accruals/release/{accrual_id}", response_class=HTMLResponse)
async def accrual_release(request: Request, accrual_id: str):
    return await _accrual_action(request, lambda s: s.release_accrual(accrual_id),
                                 lambda st: f"Released - {money(-st.variance)} back to the P&L", flash=accrual_id)


@app.post("/accruals/undo/{accrual_id}", response_class=HTMLResponse)
async def accrual_undo(request: Request, accrual_id: str):
    return await _accrual_action(request, lambda s: s.accruals.undo_settlement(accrual_id), None, delay=(0, 0.1))


@app.post("/accruals/toggle/{pid}", response_class=HTMLResponse)
async def accrual_toggle(request: Request, pid: str):
    return await _accrual_action(request, lambda s: s.accruals.toggle(pid), None, delay=(0, 0.1))


@app.post("/accruals/amount/{pid}", response_class=HTMLResponse)
async def accrual_amount(request: Request, pid: str, amount: str = Form(...)):
    value = _amount(amount)

    def action(s):
        if value is None:
            raise ValueError("That doesn't look like an amount")
        s.accruals.set_amount(pid, value)
    return await _accrual_action(request, action, None, delay=(0, 0.1))


@app.post("/accruals/manual", response_class=HTMLResponse)
async def accrual_manual(request: Request, supplier: str = Form(""), description: str = Form(""),
                         account: str = Form(""), amount: str = Form("")):
    value = _amount(amount)

    def action(s):
        if value is None:
            raise ValueError("That doesn't look like an amount")
        return s.accruals.add_manual(supplier, description, account, value)
    return await _accrual_action(request, action, lambda c: f"Accrual for {c.supplier} added")


@app.post("/accruals/manual/{pid}/remove", response_class=HTMLResponse)
async def accrual_manual_remove(request: Request, pid: str):
    return await _accrual_action(request, lambda s: s.accruals.remove_manual(pid), None, delay=(0, 0.1))


@app.post("/accruals/book", response_class=HTMLResponse)
async def accrual_book(request: Request):
    return await _accrual_action(
        request, lambda s: s.book_accruals(),
        lambda lines: f"Journal posted: {len(lines)} lines, auto-reversal scheduled", delay=(0.6, 1.2))


@app.post("/accruals/unbook", response_class=HTMLResponse)
async def accrual_unbook(request: Request):
    return await _accrual_action(request, lambda s: s.unbook_accruals(), "Booking reversed - you can edit again")


@app.post("/accruals/reclassify", response_class=HTMLResponse)
async def accrual_reclassify(request: Request):
    return await _accrual_action(request, lambda s: s.reclassify_stray(),
                                 lambda e: f"{e.ref} moved to account {e.correct_account}")


@app.post("/accruals/signoff", response_class=HTMLResponse)
async def accrual_signoff(request: Request):
    return await _accrual_action(request, lambda s: s.sign_off_accruals(),
                                 "Signed off - accrued expenses are closed for the month")


# ------------------------------------------------------------------------- shared bits


@app.get("/status-bar", response_class=HTMLResponse)
async def status_bar(request: Request):
    s, new = session_of(request)
    return render(request, "partials/status_bar.html", s, new)


@app.post("/sources/{source}/toggle", response_class=HTMLResponse)
async def toggle_source(request: Request, source: str):
    s, new = session_of(request)
    if source in SOURCES:
        if s.is_online(source):
            s.simulate_outage(source)
            toast = ("danger", f"{SOURCES[source][0]} is now offline (simulated for 45 s)")
        else:
            s.restore(source)
            toast = ("success", f"{SOURCES[source][0]} is back online")
    else:
        toast = None
    return render(request, "partials/status_bar.html", s, new, toast=toast, events=("sources-changed",))


@app.get("/activity", response_class=HTMLResponse)
async def activity(request: Request):
    s, new = session_of(request)
    return render(request, "partials/activity.html", s, new)


@app.get("/missions", response_class=HTMLResponse)
async def missions(request: Request):
    s, new = session_of(request)
    return render(request, "partials/missions.html", s, new)


@app.post("/reset")
async def reset(request: Request):
    s = store.reset(request.cookies.get(COOKIE))
    resp = Response(status_code=204, headers={"HX-Redirect": "/demo"})
    resp.set_cookie(COOKIE, s.id, httponly=True, samesite="lax", max_age=3 * 3600)
    return resp


@app.get("/author")
async def author():
    return RedirectResponse("/", status_code=301)


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    s, new = session_of(request)
    return render(request, "about.html", s, new, page="about")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "sessions": len(store)}
