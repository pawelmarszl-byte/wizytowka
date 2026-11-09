"""Render a bank statement as a PDF (fictional "Harbor Bank") and read it back.

The reader is a real parser working on the extracted PDF text - the demo does not cheat by
reading the generator's data. One line on one statement is printed in a legacy format the
parser does not understand, which is how the "statement doesn't add up" check gets triggered.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from fpdf import FPDF
from pypdf import PdfReader

from .models import Statement

BANK_NAME = "Harbor Bank"
HOLDER = "Ledgerly Demo Ltd."
IBAN = "XX00 HRBR 0000 4417 2026 0001"

NAVY = (17, 45, 78)
TEAL = (20, 150, 140)
GREY = (110, 117, 128)
LIGHT = (240, 243, 247)


def _fmt(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def render_statement_pdf(st: Statement) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_title(f"{BANK_NAME} statement {st.code}")
    pdf.set_author(BANK_NAME)
    pdf.add_page()

    # Bank logo: a simple wave mark drawn with shapes, no image assets needed.
    pdf.set_fill_color(*NAVY)
    pdf.rect(15, 14, 11, 11, style="F")
    pdf.set_draw_color(255, 255, 255)
    pdf.set_line_width(0.9)
    for dy in (3.5, 6.5):
        pdf.line(17, 14 + dy + 1, 20.5, 14 + dy)
        pdf.line(20.5, 14 + dy, 24, 14 + dy + 1)
    pdf.set_xy(29, 14)
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(*NAVY)
    pdf.cell(80, 7, BANK_NAME)
    pdf.set_xy(29, 20.5)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GREY)
    pdf.cell(80, 4, "Fictional bank - demo data only")

    pdf.set_xy(120, 14)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*NAVY)
    pdf.cell(75, 7, "Account statement", align="R")
    pdf.set_xy(120, 20.5)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GREY)
    pdf.cell(75, 4, f"No. {st.code}", align="R")

    pdf.set_draw_color(*TEAL)
    pdf.set_line_width(0.6)
    pdf.line(15, 30, 195, 30)

    # Account details box.
    pdf.set_fill_color(*LIGHT)
    pdf.rect(15, 34, 180, 26, style="F")
    pdf.set_text_color(30, 30, 30)
    rows = [
        ("Account holder", HOLDER),
        ("IBAN", IBAN),
        ("Statement date", f"{st.day:%d.%m.%Y}"),
        ("Currency", "EUR"),
    ]
    y = 37
    for label, value in rows:
        pdf.set_xy(19, y)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(38, 5, label)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(100, 5, value)
        y += 5.5

    # Balance summary - the parser reads these two lines.
    pdf.set_xy(15, 66)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(60, 6, f"Opening balance: {_fmt(st.opening)}")
    pdf.set_xy(135, 66)
    pdf.cell(60, 6, f"Closing balance: {_fmt(st.closing)}", align="R")

    # Transactions table.
    widths = (24, 30, 86, 20, 20)
    headers = ("Date", "Reference", "Description", "Amount", "Balance")
    pdf.set_xy(15, 76)
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8.5)
    for w, h in zip(widths, headers):
        pdf.cell(w, 7, h, fill=True, align="R" if h in ("Amount", "Balance") else "L")
    pdf.ln()

    running = st.opening
    pdf.set_font("Helvetica", "", 8.5)
    for i, t in enumerate(st.transactions):
        running += t.amount
        pdf.set_x(15)
        pdf.set_fill_color(*(LIGHT if i % 2 else (255, 255, 255)))
        pdf.set_text_color(30, 30, 30)
        if t.ref == st.garbled_ref:
            # Legacy SWIFT-style formatting the parser doesn't support.
            amount_text = f"{abs(t.amount):,.2f}".replace(",", " ").replace(".", ",") + (" DR" if t.amount < 0 else " CR")
            pdf.cell(widths[0], 6, f"{t.day:%y%m%d}", fill=True)
        else:
            amount_text = _fmt(t.amount)
            pdf.cell(widths[0], 6, f"{t.day:%d.%m.%Y}", fill=True)
        pdf.cell(widths[1], 6, t.ref, fill=True)
        pdf.cell(widths[2], 6, t.description[:58], fill=True)
        pdf.set_text_color(*((180, 40, 40) if t.amount < 0 else (20, 110, 70)))
        pdf.cell(widths[3], 6, amount_text, fill=True, align="R")
        pdf.set_text_color(30, 30, 30)
        pdf.cell(widths[4], 6, _fmt(running), fill=True, align="R")
        pdf.ln()

    pdf.ln(4)
    pdf.set_x(15)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(140, 6, f"Number of transactions: {len(st.transactions)}")
    pdf.cell(40, 6, f"Net change: {_fmt(st.net)}", align="R")

    pdf.set_y(-22)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(0, 3.5, f"{BANK_NAME} is a fictional institution created for the Ledgerly portfolio demo. "
                            "All names, accounts and amounts on this document are randomly generated.", align="C")

    return bytes(pdf.output())


# --------------------------------------------------------------------------- parsing


@dataclass
class ParsedLine:
    day: date
    ref: str
    description: str
    amount: Decimal


@dataclass
class ParsedStatement:
    statement_date: date | None
    opening: Decimal | None
    closing: Decimal | None
    lines: list[ParsedLine] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)  # raw text of lines we couldn't parse

    @property
    def parsed_total(self) -> Decimal:
        return sum((l.amount for l in self.lines), Decimal("0"))

    @property
    def gap(self) -> Decimal | None:
        """closing - (opening + lines). Zero means every transaction was read correctly."""
        if self.opening is None or self.closing is None:
            return None
        return self.closing - self.opening - self.parsed_total


_NUM = r"-?[\d,]+\.\d{2}"
_LINE = re.compile(rf"^(\d{{2}}\.\d{{2}}\.\d{{4}})\s+(HB\d+)\s+(.+?)\s+({_NUM})\s+({_NUM})$")
_REF_ANYWHERE = re.compile(r"\bHB\d+\b")
_OPENING = re.compile(rf"Opening balance:\s*({_NUM})")
_CLOSING = re.compile(rf"Closing balance:\s*({_NUM})")
_DATE = re.compile(r"Statement date\s*(\d{2}\.\d{2}\.\d{4})")


def _num(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def parse_statement_pdf(data: bytes) -> ParsedStatement:
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    def first(rx: re.Pattern[str]):
        m = rx.search(text)
        return m.group(1) if m else None

    opening, closing, day = first(_OPENING), first(_CLOSING), first(_DATE)
    result = ParsedStatement(
        statement_date=datetime.strptime(day, "%d.%m.%Y").date() if day else None,
        opening=_num(opening) if opening else None,
        closing=_num(closing) if closing else None,
    )
    for raw in text.splitlines():
        line = raw.strip()
        m = _LINE.match(line)
        if m:
            result.lines.append(ParsedLine(datetime.strptime(m.group(1), "%d.%m.%Y").date(),
                                           m.group(2), m.group(3), _num(m.group(4))))
        elif _REF_ANYWHERE.search(line):
            result.unreadable.append(line)
    return result
