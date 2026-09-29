"""Read-only SQL over the Chinook sales database. Owned by the ``chinook-analyst`` subagent.

Two code-layer guarantees, independent of any prompt:
* the connection is opened read-only at the driver level (``mode=ro``), so no prompt
  injection and no model mistake can turn a query into a mutation;
* results are capped and say so, so the model never mistakes a page for the whole answer
  (a lesson from round 2's evals: a truncated result read as "AC/DC has 1 album").
"""

from __future__ import annotations

import sqlite3
from typing import Any

from langchain.tools import tool

from config import CHINOOK_DB

MAX_ROWS = 50


def query(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Parameterized read used by tools, middleware and evals."""
    conn = sqlite3.connect(f"file:{CHINOOK_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


@tool
def describe_schema() -> str:
    """List the tables and columns of the Chinook sales database.

    Call this before writing SQL if you are unsure of a table or column name. Key tables:
    Customer (SupportRepId -> Employee), Employee, Invoice, InvoiceLine, Track, Album,
    Artist, Genre, MediaType, Playlist, PlaylistTrack.
    """
    tables = query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    out = []
    for t in tables:
        cols = query(f'PRAGMA table_info("{t["name"]}")')
        out.append(f"{t['name']}(" + ", ".join(f"{c['name']} {c['type']}" for c in cols) + ")")
    return "\n".join(out)


@tool
def run_sql(sql: str) -> str:
    """Run ONE read-only SQL SELECT against the Chinook sales database and return the rows.

    Use for sales analytics: revenue by country/genre/rep, a customer's invoices, top tracks,
    catalog prices. Write a single SELECT (a leading WITH is fine); no writes are possible.
    Results are capped at 50 rows and the header tells you the true total, so aggregate in
    SQL (GROUP BY, SUM, COUNT) instead of paging through raw rows.
    """
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned.lower().startswith(("select", "with")):
        return "Rejected: only read-only SELECT queries are allowed."
    if ";" in cleaned:
        return "Rejected: only a single statement is allowed."
    try:
        rows = query(cleaned)
    except sqlite3.Error as e:
        return f"Query error: {e}"
    if not rows:
        return "Query returned no rows."
    cols = list(rows[0].keys())
    out = [f"{len(rows)} rows" + (f" (showing first {MAX_ROWS})" if len(rows) > MAX_ROWS else "") + ":"]
    out.append(" | ".join(cols))
    out += [" | ".join(str(r[c]) for c in cols) for r in rows[:MAX_ROWS]]
    return "\n".join(out)


SQL_TOOLS = [describe_schema, run_sql]
