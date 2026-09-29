"""Custom middleware: the control layer that runs around every model and tool call.

LangChain v1 middleware hooks, in the order they fire inside the agent loop:

    before_agent ─▶ [ before_model ─▶ wrap_model_call(model) ─▶ after_model
                      ─▶ wrap_tool_call(tool) ]*  ─▶ after_agent

Two custom pieces live here; the built-ins (memory, PII, fallback, call limits, human-in-
the-loop, summarization, todos, filesystem, skills, subagents) are configured in agent.py.

1. ``RepContextMiddleware``   before_agent: identity check, fails closed.
                              wrap_model_call: context engineering, a small per-user
                              section appended to the system prompt (name, territory, date).
2. ``AuditTrailMiddleware``   wrap_tool_call: every side-effecting tool call (payments,
                              refunds, outgoing mail) is written to the ledger's audit log
                              with its outcome and the signed-in rep.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from functools import cache
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import SystemMessage
from langgraph.runtime import Runtime

from config import Context
from tools.ledger import audit
from tools.sql import query, query_one


def _rep_id(runtime: Runtime[Context] | None) -> int | None:
    ctx = getattr(runtime, "context", None)
    return getattr(ctx, "rep_id", None) if ctx is not None else None


@cache
def rep_profile(rep_id: int) -> dict[str, Any] | None:
    """Small, stable facts about the signed-in rep, used to personalize the prompt."""
    rep = query_one("SELECT EmployeeId, FirstName, LastName, Title, Email FROM Employee WHERE EmployeeId = ?", (rep_id,))
    if not rep:
        return None
    territory = query(
        "SELECT Country, COUNT(*) AS n FROM Customer WHERE SupportRepId = ? GROUP BY Country ORDER BY n DESC, Country",
        (rep_id,),
    )
    return {**rep, "countries": [t["Country"] for t in territory], "customers": sum(t["n"] for t in territory)}


def append_to_system_message(system: SystemMessage | None, text: str) -> SystemMessage:
    """Append a section without dropping what other middleware (memory, skills) already added."""
    blocks = list(system.content_blocks) if system else []
    blocks.append({"type": "text", "text": f"\n\n{text}" if blocks else text})
    return SystemMessage(content_blocks=blocks)


# ── 1. Identity + context engineering ─────────────────────────────────────────
class RepContextMiddleware(AgentMiddleware):
    """Refuse to start without a known sales rep in the run context, then tell the model
    who it is working for. Identity never comes from the conversation, so the model cannot
    be talked into acting as someone else."""

    def _verify(self, runtime: Runtime[Context]) -> None:
        rep_id = _rep_id(runtime)
        if rep_id is None:
            raise PermissionError('No rep_id in the run context. In Studio, set context to {"rep_id": 3} (Jane Peacock).')
        if rep_profile(rep_id) is None:
            raise PermissionError(f"Unknown rep_id {rep_id}: access denied.")

    def before_agent(self, state: Any, runtime: Runtime[Context]) -> dict[str, Any] | None:
        self._verify(runtime)
        return None

    async def abefore_agent(self, state: Any, runtime: Runtime[Context]) -> dict[str, Any] | None:
        await asyncio.to_thread(self._verify, runtime)  # keep sqlite off the event loop
        return None

    @staticmethod
    def _section(runtime: Runtime[Context]) -> str | None:
        rep_id = _rep_id(runtime)
        p = rep_profile(rep_id) if rep_id is not None else None
        if not p:
            return None
        countries = ", ".join(p["countries"][:8]) + (" and more" if len(p["countries"]) > 8 else "")
        return (
            "## Signed-in user\n"
            f"- {p['FirstName']} {p['LastName']}, {p['Title']} ({p['Email']}), employee id {p['EmployeeId']}\n"
            f"- Territory: {p['customers']} customers in {countries}\n"
            f"- Today: {date.today().isoformat()}\n"
            "Address them by first name. Sign outgoing mail with their name. 'My territory' means "
            "customers whose SupportRepId is their employee id."
        )

    def _apply(self, request: ModelRequest) -> ModelRequest:
        section = self._section(request.runtime)
        if section is None:
            return request
        return request.override(system_message=append_to_system_message(request.system_message, section))

    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return handler(self._apply(request))

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return await handler(await asyncio.to_thread(self._apply, request))


# ── 2. Audit trail for side effects ───────────────────────────────────────────
AUDITED_TOOLS = frozenset({"pay_invoice", "issue_refund", "send_email"})


def _outcome(result: Any) -> str:
    text = getattr(result, "text", None)  # a ToolMessage; a Command has no text
    return text if isinstance(text, str) and text else str(result)


class AuditTrailMiddleware(AgentMiddleware):
    """Record who did what: the rep, the tool, its arguments and the outcome.

    Runs *after* the human-in-the-loop gate, so a call reaches this hook only once a
    person has approved it (rejections never execute, and are visible in the trace).
    """

    def _record(self, request: ToolCallRequest, result: Any) -> None:
        call = request.tool_call
        audit(_rep_id(request.runtime), call["name"], json.dumps(call.get("args", {}), default=str), _outcome(result))

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        result = handler(request)
        if request.tool_call["name"] in AUDITED_TOOLS:
            self._record(request, result)
        return result

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        result = await handler(request)
        if request.tool_call["name"] in AUDITED_TOOLS:
            await asyncio.to_thread(self._record, request, result)
        return result
