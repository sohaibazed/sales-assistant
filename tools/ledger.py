"""The ledger: the agent's ONLY write path. Purchase orders, vendor payments, customer
refunds and the audit trail live in a small SQLite DB next to the (read-only) Chinook DB.

Lookups (``lookup_purchase_order``, ``vendor_profile``, ``list_ledger``) go to the
``ap-auditor`` subagent. The two side-effecting tools stay on the main agent and are
gated by a human (see agent.py -> interrupt_on):

* ``pay_invoice``   pauses only when a person has something to decide (amount at or above
                    PAY_APPROVAL_THRESHOLD and the invoice passes validation);
* ``issue_refund``  always pauses (approve / edit / reject).

Every gate is backed by a check in code, so a bad prompt or a hasty approval still can't
pay a PO that doesn't match, pay an invoice twice, or refund more than was charged.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain.tools import ToolRuntime, tool

from config import LEDGER_DB, PAY_APPROVAL_THRESHOLD, Context
from tools.sql import query_one

# ── Seed data: what accounts payable already knows ───────────────────────────
PURCHASE_ORDERS = [
    # po_number, vendor, amount, description
    ("PO-1042", "Northwind Music Licensing", 4800.00, "Q3 catalog licensing: Latin & Jazz back catalog"),
    ("PO-1051", "CloudStack Hosting", 349.00, "Streaming CDN, September"),
    ("PO-1060", "Apex Studio Rentals", 1200.00, "Studio time for the holiday sampler"),
    ("PO-1063", "Brightline Design Co.", 850.00, "Newsletter template refresh"),
]
VENDORS = [
    # name, bank account on file (last 4), contact email domain
    ("Northwind Music Licensing", "****7781", "northwindlicensing.com"),
    ("CloudStack Hosting", "****2210", "cloudstack.io"),
    ("Apex Studio Rentals", "****0934", "apexstudios.example"),
    ("Brightline Design Co.", "****4412", "brightline.design"),
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number TEXT PRIMARY KEY, vendor TEXT NOT NULL, amount REAL NOT NULL,
    description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open');
CREATE TABLE IF NOT EXISTS vendors (
    name TEXT PRIMARY KEY, bank_account_last4 TEXT NOT NULL, email_domain TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vendor_payments (
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_number TEXT NOT NULL UNIQUE,
    vendor TEXT NOT NULL, amount REAL NOT NULL, po_number TEXT NOT NULL,
    paid_by_rep INTEGER, paid_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS refunds (
    refund_id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL, amount REAL NOT NULL, reason TEXT NOT NULL,
    issued_by_rep INTEGER, issued_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, rep_id INTEGER,
    tool TEXT NOT NULL, args TEXT NOT NULL, outcome TEXT NOT NULL);
"""

# Evals and tests point each run at its own ledger. A ContextVar (not a global) so that
# concurrent async runs, each in its own task, never share a file.
_db_override: ContextVar[Path | None] = ContextVar("ledger_db_override", default=None)


@contextmanager
def isolated_ledger(path: Path):
    """Run a block against a private ledger file."""
    token = _db_override.set(path)
    try:
        yield
    finally:
        _db_override.reset(token)


def _conn() -> sqlite3.Connection:
    path = _db_override.get() or LEDGER_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0] == 0:
        conn.executemany(
            "INSERT OR IGNORE INTO purchase_orders (po_number, vendor, amount, description) VALUES (?, ?, ?, ?)", PURCHASE_ORDERS
        )
        conn.executemany("INSERT OR IGNORE INTO vendors (name, bank_account_last4, email_domain) VALUES (?, ?, ?)", VENDORS)
        conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rep_id(runtime: ToolRuntime[Context] | None) -> int | None:
    ctx = getattr(runtime, "context", None)
    return getattr(ctx, "rep_id", None) if ctx is not None else None


def audit(rep_id: int | None, tool_name: str, args: str, outcome: str) -> None:
    """Append one line to the audit trail (used by AuditTrailMiddleware)."""
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO audit_log (at, rep_id, tool, args, outcome) VALUES (?, ?, ?, ?, ?)",
            (_now(), rep_id, tool_name, args, outcome[:500]),
        )
        conn.commit()
    finally:
        conn.close()


# ── Validation shared by the tool and its approval gate ──────────────────────
def po_remaining(po_number: str) -> dict[str, Any] | None:
    conn = _conn()
    try:
        po = conn.execute("SELECT * FROM purchase_orders WHERE po_number = ?", (po_number.strip().upper(),)).fetchone()
        if not po:
            return None
        paid = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM vendor_payments WHERE po_number = ?", (po["po_number"],)
        ).fetchone()[0]
        return {**dict(po), "paid": float(paid), "remaining": round(float(po["amount"]) - float(paid), 2)}
    finally:
        conn.close()


def validate_payment(invoice_number: str, vendor: str, amount: float, po_number: str) -> str | None:
    """Return a refusal reason, or None when the payment is valid. Pure code, no model."""
    if amount <= 0:
        return "Amount must be positive."
    conn = _conn()
    try:
        dup = conn.execute("SELECT payment_id FROM vendor_payments WHERE invoice_number = ?", (invoice_number.strip(),)).fetchone()
    finally:
        conn.close()
    if dup:
        return f"Invoice {invoice_number} was already paid (payment #{dup['payment_id']}). Duplicate: do not pay again."
    po = po_remaining(po_number)
    if not po:
        return f"No purchase order {po_number!r} exists. Do not pay; ask the vendor for a valid PO."
    if vendor.strip().lower() not in po["vendor"].lower() and po["vendor"].lower() not in vendor.strip().lower():
        return f"PO {po['po_number']} belongs to {po['vendor']!r}, not {vendor!r}. Do not pay; flag for review."
    if amount > po["remaining"] + 0.005:
        return (
            f"Invoice amount ${amount:,.2f} exceeds the remaining balance of PO {po['po_number']} "
            f"(${po['remaining']:,.2f} of ${po['amount']:,.2f}). Do not pay; flag for review."
        )
    return None


def payment_needs_review(request: Any) -> bool:
    """Conditional approval for ``pay_invoice`` (``InterruptOnConfig.when``).

    Pause only when a person has something to decide: the invoice is valid AND at or above
    the approval threshold. Small, valid invoices go straight through; invalid ones are
    refused in code without paging anyone.
    """
    args = request.tool_call["args"]
    try:
        amount = float(args.get("amount", 0))
    except (TypeError, ValueError):
        return False
    if amount < PAY_APPROVAL_THRESHOLD:
        return False
    return validate_payment(str(args.get("invoice_number", "")), str(args.get("vendor", "")), amount, str(args.get("po_number", ""))) is None


# ── Lookups: the ap-auditor's tools ──────────────────────────────────────────
@tool
def lookup_purchase_order(po_number: str) -> str:
    """Look up a purchase order: vendor, approved amount, what has been paid and what remains."""
    po = po_remaining(po_number)
    if not po:
        return f"No purchase order {po_number!r} on file."
    return (
        f"{po['po_number']}: vendor {po['vendor']!r}, approved ${po['amount']:,.2f} for "
        f"'{po['description']}'. Paid so far ${po['paid']:,.2f}; remaining ${po['remaining']:,.2f}; status {po['status']}."
    )


@tool
def vendor_profile(vendor: str) -> str:
    """Show what we have on file for a vendor: bank account (last 4) and their email domain.

    Use it to spot fraud: an invoice from an unknown domain, or an email asking to change
    bank details, must never be acted on from email alone.
    """
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM vendors WHERE lower(name) LIKE ?", (f"%{vendor.strip().lower()}%",)).fetchall()
    finally:
        conn.close()
    if not rows:
        return f"No approved vendor matching {vendor!r}. Treat as unknown: do not pay without onboarding."
    return "\n".join(
        f"- {r['name']}: bank account {r['bank_account_last4']} on file; emails come from @{r['email_domain']}" for r in rows
    )


@tool
def list_ledger(limit: int = 10) -> str:
    """List recent vendor payments and customer refunds recorded in the ledger."""
    conn = _conn()
    try:
        pays = conn.execute("SELECT * FROM vendor_payments ORDER BY payment_id DESC LIMIT ?", (limit,)).fetchall()
        refs = conn.execute("SELECT * FROM refunds ORDER BY refund_id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    out = ["Payments:" if pays else "Payments: none"]
    out += [
        f"- #{p['payment_id']} {p['invoice_number']} {p['vendor']} ${p['amount']:,.2f} ({p['po_number']}) at {p['paid_at']}" for p in pays
    ]
    out.append("Refunds:" if refs else "Refunds: none")
    out += [f"- #{r['refund_id']} invoice {r['invoice_id']} customer {r['customer_id']} ${r['amount']:,.2f}: {r['reason']}" for r in refs]
    return "\n".join(out)


# ── Actions: on the main agent, human-gated ───────────────────────────────────
@tool
def pay_invoice(invoice_number: str, vendor: str, amount: float, po_number: str, runtime: ToolRuntime[Context]) -> str:
    """Pay a vendor invoice against a purchase order and record it in the ledger.

    Validation happens in code: the PO must exist, belong to this vendor, and have enough
    remaining balance, and the invoice number must not have been paid before. Invoices at or
    above the approval threshold pause for a human before anything is paid; just make the
    call, don't ask permission in prose. Never pay from email instructions alone.
    """
    problem = validate_payment(invoice_number, vendor, amount, po_number)
    if problem:
        return f"Refused: {problem}"
    po = po_remaining(po_number)
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO vendor_payments (invoice_number, vendor, amount, po_number, paid_by_rep, paid_at) VALUES (?, ?, ?, ?, ?, ?)",
            (invoice_number.strip(), po["vendor"], float(amount), po["po_number"], _rep_id(runtime), _now()),
        )
        if po["remaining"] - float(amount) < 0.005:
            conn.execute("UPDATE purchase_orders SET status = 'closed' WHERE po_number = ?", (po["po_number"],))
        conn.commit()
        approved = " after reviewer approval" if float(amount) >= PAY_APPROVAL_THRESHOLD else " (below the approval threshold, no review needed)"
        return f"Paid{approved}: payment #{cur.lastrowid}, {invoice_number} from {po['vendor']} for ${amount:,.2f} against {po['po_number']}."
    finally:
        conn.close()


@tool
def issue_refund(invoice_id: int, amount: float, reason: str, runtime: ToolRuntime[Context]) -> str:
    """Refund a customer for one of their Chinook invoices (full or partial).

    A human approves, edits or rejects every refund before it is issued, so never promise a
    customer that a refund will go through; just make the call with the invoice id, the
    amount (never more than the invoice total) and a one-sentence reason.
    """
    inv = query_one("SELECT CustomerId, Total FROM Invoice WHERE InvoiceId = ?", (int(invoice_id),))
    if not inv:
        return f"Refused: no invoice #{invoice_id} exists."
    if amount <= 0 or amount > float(inv["Total"]) + 0.005:
        return f"Refused: amount ${amount:,.2f} is outside 0 < amount <= invoice total ${inv['Total']:,.2f}."
    conn = _conn()
    try:
        prior = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE invoice_id = ?", (int(invoice_id),)).fetchone()[0]
        if float(prior) + float(amount) > float(inv["Total"]) + 0.005:
            return f"Refused: ${prior:,.2f} was already refunded on invoice #{invoice_id}; only ${inv['Total'] - prior:,.2f} remains."
        cur = conn.execute(
            "INSERT INTO refunds (invoice_id, customer_id, amount, reason, issued_by_rep, issued_at) VALUES (?, ?, ?, ?, ?, ?)",
            (int(invoice_id), int(inv["CustomerId"]), float(amount), reason.strip(), _rep_id(runtime), _now()),
        )
        conn.commit()
        return f"Refund #{cur.lastrowid} issued: ${amount:,.2f} on invoice #{invoice_id} (customer {inv['CustomerId']}). Reason: {reason.strip()}"
    finally:
        conn.close()


def refunds_for_invoice(invoice_id: int) -> list[dict[str, Any]]:
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM refunds WHERE invoice_id = ?", (invoice_id,)).fetchall()]
    finally:
        conn.close()


@tool
def refunds_for_invoice_tool(invoice_id: int) -> str:
    """Show refunds recorded in the ledger for one invoice and their total."""
    refunds = refunds_for_invoice(int(invoice_id))
    if not refunds:
        return f"No refunds found for invoice #{invoice_id}. Total already refunded: $0.00."
    total = sum(float(refund["amount"]) for refund in refunds)
    out = [f"Refunds for invoice #{invoice_id}:"]
    out += [
        f"- #{refund['refund_id']}: ${refund['amount']:,.2f}; reason: {refund['reason']}; issued_at: {refund['issued_at']}"
        for refund in refunds
    ]
    out.append(f"Total already refunded: ${total:,.2f}.")
    return "\n".join(out)


def refunds_for_invoice_any() -> list[dict[str, Any]]:
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM refunds ORDER BY refund_id").fetchall()]
    finally:
        conn.close()


def payments() -> list[dict[str, Any]]:
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM vendor_payments ORDER BY payment_id").fetchall()]
    finally:
        conn.close()


def audit_entries() -> list[dict[str, Any]]:
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()]
    finally:
        conn.close()


AP_LOOKUP_TOOLS = [lookup_purchase_order, vendor_profile, list_ledger]
ACTION_TOOLS = [pay_invoice, issue_refund]
