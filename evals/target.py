"""Eval target: run one dataset example through the assistant and return what the
evaluators need (answer, every tool call including the specialists', tool results, which
actions paused for a human, the ledger afterwards, and any deliverables written).

Each example runs in isolation: a fresh thread, a private ledger and a reset mailbox.
Human-in-the-loop: when a run pauses, the target records the pending action(s) and resumes
with "approve", the way a reviewer would, so the example still reaches a final answer.
Evaluators then check *that* the right action paused, and what the ledger shows.

The mailbox and output/ are shared state (one mail server, one folder), so experiments run
examples sequentially by default (--concurrency 1).
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from config import OUTPUT_DIR, REPO_ROOT, Context  # noqa: E402
from tools import ledger  # noqa: E402
from tools.mail import discover_mail_tools, reset_mailbox  # noqa: E402

MAX_APPROVALS = 4
MANUAL = REPO_ROOT / "AGENTS.md"


def _text(msg: Any) -> str:
    t = getattr(msg, "text", "")
    return t if isinstance(t, str) else str(msg.content)


async def run_example(build: Callable[..., Any], mail_tools: list, context: Context, question: str) -> dict[str, Any]:
    """Run one example in isolation and collect everything the evaluators look at."""
    await reset_mailbox(mail_tools)
    started = time.time()
    manual = MANUAL.read_text()  # AGENTS.md is shared state too: an edit must not leak into later examples
    try:
        with ledger.isolated_ledger(Path(tempfile.gettempdir()) / f"sales-assistant-ledger-{uuid.uuid4()}.sqlite"):
            result = await _run(build(mail_tools=mail_tools, checkpointer=InMemorySaver()), context, question)
            result["ledger"] = {
                "payments": [p["invoice_number"] for p in ledger.payments()],
                "refunds": [r["invoice_id"] for r in ledger.refunds_for_invoice_any()],
            }
    finally:
        result_manual = MANUAL.read_text()
        if result_manual != manual:
            MANUAL.write_text(manual)
    result["memory_edited"] = result_manual != manual
    result["deliverables"] = {
        p.name: (p.read_text(errors="replace") if p.suffix == ".html" else f"<{p.stat().st_size} bytes>")
        for p in OUTPUT_DIR.glob("*")
        if p.is_file() and p.name != ".gitkeep" and p.stat().st_mtime >= started - 1
    }
    return result


async def _run(agent: Any, context: Context, question: str) -> dict[str, Any]:
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 150}
    tool_calls: list[dict] = []
    tool_results: list[str] = []
    interrupts: list[dict] = []
    seen_calls: set[str] = set()
    seen_results: set[str] = set()
    payload: Any = {"messages": [HumanMessage(question)]}

    for _ in range(MAX_APPROVALS + 1):
        async for namespace, update in agent.astream(payload, config, context=context, stream_mode="updates", subgraphs=True):
            where = "main" if not namespace else "specialist"
            for value in (update or {}).values():
                if not isinstance(value, dict):
                    continue
                for msg in value.get("messages") or []:
                    if isinstance(msg, AIMessage):
                        for call in msg.tool_calls:
                            if call["id"] not in seen_calls:
                                seen_calls.add(call["id"])
                                tool_calls.append({"name": call["name"], "args": call["args"], "agent": where})
                    elif isinstance(msg, ToolMessage) and msg.tool_call_id not in seen_results:
                        seen_results.add(msg.tool_call_id)
                        tool_results.append(f"[{msg.name}] {_text(msg)}")
        pending = (await agent.aget_state(config)).interrupts
        if not pending:
            break
        decisions = []
        for intr in pending:
            for action in intr.value.get("action_requests", []):
                interrupts.append({"name": action["name"], "args": action["args"]})
                decisions.append({"type": "approve"})
        payload = Command(resume={"decisions": decisions})

    messages = (await agent.aget_state(config)).values.get("messages", [])
    final = next((m for m in reversed(messages) if isinstance(m, AIMessage) and _text(m).strip()), None)
    return {
        "answer": _text(final) if final else "",
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "interrupts": interrupts,
    }


# ── The system under test, with variants for A/B experiments ─────────────────
def assistant_target(*, main_model: str | None = None, subagent_model: str | None = None, use_skills: bool = True):
    """Returns an async target(inputs) -> outputs for `aevaluate`."""
    from agent import build_agent

    mail_tools: list | None = None

    def build(**kw):
        return build_agent(main_model=main_model, subagent_model=subagent_model, use_skills=use_skills, **kw)

    async def target(inputs: dict) -> dict:
        nonlocal mail_tools
        if mail_tools is None:
            mail_tools = await discover_mail_tools()
            if not mail_tools:
                raise RuntimeError("Mail MCP server not running: python mcp/mail_server.py")
        return await run_example(build, mail_tools, Context(rep_id=inputs["rep_id"]), inputs["question"])

    return target


if __name__ == "__main__":  # quick manual check: python -m evals.target "Pay the CloudStack invoice CS-77213 for $349 against PO-1051"
    q = " ".join(sys.argv[1:]) or "What was our total revenue in 2025?"
    out = asyncio.run(assistant_target()({"question": q, "rep_id": 3}))
    out["deliverables"] = list(out["deliverables"])
    print(json.dumps(out, indent=2, default=str))
