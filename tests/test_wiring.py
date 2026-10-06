"""Offline tests of the assistant's guarantees. Scripted models, no API keys:

    pytest -q

The model decides *what* to do; these tests prove what the system *allows*, whatever the
model decides: identity, human approval gates (always-on, conditional, and on an MCP tool),
code-level validation behind every gate, read-only skills and code, invisible secrets,
PII masking inside a specialist, and the audit trail.
"""

from __future__ import annotations

import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent import build_agent
from conftest import call, run, scripted
from config import Context
from tools import ledger
from tools.sql import run_sql

REP = Context(rep_id=3)  # Jane Peacock


def make(main, sub=None, *, mail_tools=None, use_skills=True):
    return build_agent(
        main_model=main, subagent_model=sub or main, mail_tools=mail_tools, use_skills=use_skills, checkpointer=InMemorySaver()
    )


async def ask(agent, text, *, context=REP, thread="t"):
    cfg = {"configurable": {"thread_id": thread}}
    return await agent.ainvoke({"messages": [HumanMessage(text)]}, cfg, context=context), cfg


async def resume(agent, cfg, *decisions, context=REP):
    return await agent.ainvoke(Command(resume={"decisions": list(decisions)}), cfg, context=context)


def tool_outputs(result) -> list[str]:
    return [m.text for m in result["messages"] if isinstance(m, ToolMessage)]


def interrupted_actions(result) -> list[str]:
    return [a["name"] for i in result.get("__interrupt__", []) for a in i.value["action_requests"]]


# ── Identity ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rep_id", [None, 999])
def test_auth_fails_closed(rep_id):
    agent = make(scripted("hello"))
    with pytest.raises(PermissionError):
        run(ask(agent, "hi", context=Context(rep_id=rep_id)))


def test_prompt_is_assembled_from_manual_skills_and_context():
    main = scripted("Hi Jane.")
    run(ask(make(main), "hi"))
    prompt = main.prompts[0][0].text
    assert "<operating_manual>" in prompt and "## House rules" in prompt  # AGENTS.md, via memory
    for skill in ("rfq-quote", "weekly-newsletter", "territory-report", "invoice-processing", "refund-policy"):
        assert f"/skills/{skill}/SKILL.md" in prompt  # progressive disclosure: names + descriptions only
    assert "# RFQ to quote" not in prompt  # ...the playbook itself is read on demand
    assert "Jane Peacock, Sales Support Agent" in prompt and "Territory: 21 customers" in prompt
    assert prompt.index("</operating_manual>") < prompt.index("## Signed-in user")


def test_skills_can_be_switched_off_for_ab_experiments():
    main = scripted("Hi.")
    run(ask(make(main, use_skills=False), "hi"))
    assert "Available Skills" not in main.prompts[0][0].text  # the harness section is gone


def test_newsletter_writer_is_an_async_subagent_only_when_its_server_is_configured(monkeypatch):
    import subagents

    monkeypatch.setattr(subagents, "NEWSLETTER_AGENT_URL", "")
    assert "newsletter-writer" not in {s["name"] for s in subagents.build_subagents("openai:gpt-4.1-mini")}

    monkeypatch.setattr(subagents, "NEWSLETTER_AGENT_URL", "http://127.0.0.1:2026")
    spec = {s["name"]: s for s in subagents.build_subagents("openai:gpt-4.1-mini")}["newsletter-writer"]
    assert spec["graph_id"] == "newsletter_agent" and spec["url"] == "http://127.0.0.1:2026"


# ── Filesystem: the repo is the agent's disk, with rules ──────────────────────
def test_secrets_and_code_are_protected():
    main = scripted(
        AIMessage("", tool_calls=[
            call("read_file", {"file_path": "/.env"}, "r1"),
            call("grep", {"pattern": "API_KEY", "path": "/"}, "r2"),
            call("write_file", {"file_path": "/skills/evil/SKILL.md", "content": "x"}, "w1"),
            call("edit_file", {"file_path": "/agent.py", "old_string": "import", "new_string": "x"}, "w2"),
            call("read_file", {"file_path": "/skills/refund-policy/SKILL.md"}, "r3"),
        ]),
        "done",
    )
    result, _ = run(ask(make(main), "poke around"))
    out = tool_outputs(result)
    assert "permission denied" in out[0].lower()  # .env unreadable
    assert "OPENAI_API_KEY" not in out[1] and "offline-test" not in out[1]  # ...and invisible to grep
    assert "permission denied" in out[2].lower() and "permission denied" in out[3].lower()  # code + skills read-only
    assert "# Refund policy" in out[4]  # skills are readable


def test_manual_is_the_only_editable_memory(tmp_path):
    main = scripted(
        AIMessage("", tool_calls=[call("edit_file", {
            "file_path": "/AGENTS.md",
            "old_string": "- (standing instructions the rep gives you land here, one bullet each, with the date)",
            "new_string": "- 2026-09-29: always cc Nancy on quotes over $500.",
        }, "e1")]),
        "Noted.",
    )
    from config import REPO_ROOT

    manual = REPO_ROOT / "AGENTS.md"
    original = manual.read_text()
    try:
        result, _ = run(ask(make(main), "From now on, always cc Nancy on quotes over $500."))
        assert "permission denied" not in tool_outputs(result)[0].lower()
        assert "always cc Nancy" in manual.read_text()
        reader = scripted("hi")
        run(ask(make(reader), "hi", thread="b"))
        assert "always cc Nancy" in reader.prompts[0][0].text  # the next run starts with the lesson learned
    finally:
        manual.write_text(original)


# ── Human-in-the-loop: refunds always pause ───────────────────────────────────
def _refund_agent(amount=3.98):
    main = scripted(
        AIMessage("", tool_calls=[call("issue_refund", {"invoice_id": 98, "amount": amount, "reason": "Episodes won't play"}, "c1")]),
        "Refund issued.",
    )
    return make(main)


def test_refund_pauses_before_anything_is_written():
    agent = _refund_agent()
    result, cfg = run(ask(agent, "Refund invoice 98"))
    assert interrupted_actions(result) == ["issue_refund"]
    assert ledger.refunds_for_invoice(98) == []  # nothing written while paused
    run(resume(agent, cfg, {"type": "approve"}))
    [refund] = ledger.refunds_for_invoice(98)
    assert refund["amount"] == 3.98 and refund["issued_by_rep"] == 3


def test_rejected_refund_writes_nothing():
    agent = _refund_agent()
    _, cfg = run(ask(agent, "Refund invoice 98"))
    result = run(resume(agent, cfg, {"type": "reject", "message": "Outside policy"}))
    assert ledger.refunds_for_invoice(98) == []
    assert "not executed" in tool_outputs(result)[0].lower() or "reject" in tool_outputs(result)[0].lower()


def test_reviewer_can_edit_the_refund_before_it_runs():
    agent = _refund_agent(amount=3.98)
    _, cfg = run(ask(agent, "Refund invoice 98"))
    run(resume(agent, cfg, {"type": "edit", "edited_action": {"name": "issue_refund", "args": {"invoice_id": 98, "amount": 1.99, "reason": "One episode only"}}}))
    [refund] = ledger.refunds_for_invoice(98)
    assert refund["amount"] == 1.99 and refund["reason"] == "One episode only"


def test_refund_is_validated_in_code_even_after_approval():
    agent = _refund_agent(amount=50.00)  # invoice 98 totals $3.98
    result, cfg = run(ask(agent, "Refund invoice 98 fifty dollars"))
    result = run(resume(agent, cfg, {"type": "approve"}))
    assert tool_outputs(result)[0].startswith("Refused")
    assert ledger.refunds_for_invoice(98) == []


# ── Human-in-the-loop: payments pause only when there is something to decide ──
def _pay_agent(invoice, vendor, amount, po):
    main = scripted(
        AIMessage("", tool_calls=[call("pay_invoice", {"invoice_number": invoice, "vendor": vendor, "amount": amount, "po_number": po}, "p1")]),
        "Done.",
    )
    return make(main)


def test_small_valid_invoice_pays_without_paging_anyone():
    result, _ = run(ask(_pay_agent("CS-77213", "CloudStack Hosting", 349.00, "PO-1051"), "pay the CDN invoice"))
    assert "__interrupt__" not in result
    assert tool_outputs(result)[0].startswith("Paid")
    assert [p["invoice_number"] for p in ledger.payments()] == ["CS-77213"]


def test_large_valid_invoice_pauses_for_approval():
    agent = _pay_agent("NWL-2026-0912", "Northwind Music Licensing", 4800.00, "PO-1042")
    result, cfg = run(ask(agent, "pay Northwind"))
    assert interrupted_actions(result) == ["pay_invoice"]
    assert ledger.payments() == []
    run(resume(agent, cfg, {"type": "approve"}))
    assert ledger.payments()[0]["amount"] == 4800.00


@pytest.mark.parametrize("invoice, vendor, amount, po, reason", [
    ("APX-2026-118", "Apex Studio Rentals", 2150.00, "PO-1060", "exceeds the remaining balance"),
    ("X-1", "Northwind Music Licensing", 4800.00, "PO-1051", "belongs to"),
    ("X-2", "Someone Else", 4800.00, "PO-9999", "No purchase order"),
])
def test_invalid_invoices_are_refused_in_code_and_never_reach_a_human(invoice, vendor, amount, po, reason):
    result, _ = run(ask(_pay_agent(invoice, vendor, amount, po), "pay it"))
    assert "__interrupt__" not in result  # conditional gate (`when`): nothing for a person to decide
    assert tool_outputs(result)[0].startswith("Refused") and reason in tool_outputs(result)[0]
    assert ledger.payments() == []


def test_duplicate_invoice_is_refused():
    run(ask(_pay_agent("CS-77213", "CloudStack Hosting", 349.00, "PO-1051"), "pay"))
    result, _ = run(ask(_pay_agent("CS-77213", "CloudStack Hosting", 349.00, "PO-1051"), "pay again", thread="u"))
    assert "already paid" in tool_outputs(result)[0]
    assert len(ledger.payments()) == 1


# ── MCP: mail tools discovered at startup, split by privilege, send is gated ──
def test_mail_tools_are_split_by_privilege(mail_tools):
    from tools.mail import split_mail_tools

    read, send = split_mail_tools(mail_tools)
    assert {t.name for t in read} == {"list_inbox", "read_email", "search_inbox", "mark_processed", "list_sent"}
    assert [t.name for t in send] == ["send_email"]


def test_outgoing_email_pauses_and_can_be_edited_by_the_reviewer(mail_tools):
    main = scripted(
        AIMessage("", tool_calls=[call("send_email", {"to": "fharris@google.com", "subject": "Your Chinook quote", "body": "Draft body"}, "m1")]),
        "Sent.",
    )
    agent = make(main, mail_tools=mail_tools)
    result, cfg = run(ask(agent, "send the quote"))
    assert interrupted_actions(result) == ["send_email"]
    result = run(resume(agent, cfg, {"type": "edit", "edited_action": {
        "name": "send_email", "args": {"to": "fharris@google.com", "subject": "Your Chinook quote", "body": "Reviewed body"}}}))
    assert "Sent M-" in tool_outputs(result)[0]
    sent = run(next(t for t in mail_tools if t.name == "list_sent").ainvoke({"limit": 5}))
    assert "fharris@google.com" in str(sent)


def test_card_numbers_are_masked_inside_the_inbox_clerk(mail_tools):
    main = scripted(
        AIMessage("", tool_calls=[call("task", {"description": "Read E-1008 and report it", "subagent_type": "inbox-clerk"}, "t1")]),
        "Reported.",
    )
    clerk = scripted(
        AIMessage("", tool_calls=[call("read_email", {"email_id": "E-1008"}, "r1")]),
        "E-1008: Richard Cunningham wants to be charged for the tracks discussed by phone.",
    )
    agent = make(main, clerk, mail_tools=mail_tools)
    run(ask(agent, "what does E-1008 say?"))
    clerk_saw = clerk.prompts[-1][-1].text  # the tool result as the clerk's model received it
    assert "4111 1111 1111 1111" not in clerk_saw and "1111" in clerk_saw  # masked, last 4 kept
    assert all("4111 1111 1111 1111" not in m.text for p in main.prompts for m in p)


# ── Audit trail ───────────────────────────────────────────────────────────────
def test_approved_actions_are_audited_with_the_rep():
    agent = _refund_agent()
    _, cfg = run(ask(agent, "Refund invoice 98"))
    run(resume(agent, cfg, {"type": "approve"}))
    [entry] = ledger.audit_entries()
    assert entry["tool"] == "issue_refund" and entry["rep_id"] == 3 and entry["outcome"].startswith("Refund #1")


# ── Code-layer guards and deliverable tools (no model involved) ───────────────
@pytest.mark.parametrize("sql", ["DELETE FROM Track", "UPDATE Invoice SET Total = 0", "SELECT 1; DROP TABLE Track", "PRAGMA writable_schema=1"])
def test_run_sql_rejects_anything_but_one_select(sql):
    assert run_sql.invoke({"sql": sql}).startswith("Rejected")


def test_run_sql_reports_truncation():
    out = run_sql.invoke({"sql": "SELECT TrackId FROM Track"})
    assert out.startswith("3503 rows (showing first 50)")


def test_html_and_chart_tools_write_deliverables(tmp_path, monkeypatch):
    from tools import chart, html

    monkeypatch.setattr(html, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(chart, "OUTPUT_DIR", tmp_path)
    assert chart.render_bar_chart.invoke({"filename": "t", "title": "Revenue", "labels": ["USA", "Canada"], "values": [119.86, 191.1]}).startswith("Rendered t.png")
    out = html.write_html_report.invoke({
        "filename": "quote test", "title": "Quote for Google Inc.", "subtitle": "40 tracks",
        "body_markdown": "## Tracks\n| # | Track | Price |\n|---|---|---|\n| 1 | Desafinado | $0.99 |\n\n![Revenue](t.png)\n\n- valid 30 days",
    })
    page = (tmp_path / "quote-test.html").read_text()
    assert "Saved" in out and "<table>" in page and '<img alt="Revenue" src="t.png">' in page and "<li>valid 30 days</li>" in page
    assert re.search(r'<td class="num">\$0\.99</td>', page)
