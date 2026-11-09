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
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .domain.models import CHART_OF_ACCOUNTS, POSTABLE_ACCOUNTS
from .domain.reconciliation import KIND_TITLES
from .state import SOURCES, DemoSession, SessionStore, SourceOffline, month, statement_pdf
from .web.chart import balance_chart

BASE = Path(__file__).parent
COOKIE = "ledgerly_session"
# Simulated network latency; set LEDGERLY_FAST=1 (tests) to skip it.
FAST = os.environ.get("LEDGERLY_FAST") == "1"

app = FastAPI(title="Ledgerly", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
store = SessionStore()


def money(v, signed: bool = False) -> str:
    v = Decimal(v)
    sign = "+" if signed and v > 0 else ("−" if v < 0 else "")
    return f"{sign}€{abs(v):,.2f}"


templates.env.filters["money"] = money
templates.env.globals.update(ACCOUNTS=CHART_OF_ACCOUNTS, POSTABLE=POSTABLE_ACCOUNTS, SOURCES=SOURCES,
                             KIND_TITLES=KIND_TITLES)


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
    return templates.TemplateResponse(request, "home.html", {})


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
