"""Chinook Sales Assistant: a Deep Agent that assembles the whole stack in one place.

    sales rep ──▶ sales-assistant  (create_deep_agent, main model)
                    middleware: memory (AGENTS.md) ▸ rep context ▸ PII ▸ audit ▸ fallback ▸ limits
                    harness:    todos ▸ files (this repo) ▸ skills (/skills/) ▸ summarization ▸ HITL
                    tools:      write_html_report, render_bar_chart,
                                pay_invoice ⏸ (conditional), issue_refund ⏸, send_email ⏸ (MCP)
                    ├─▶ chinook-analyst   run_sql, describe_schema        (read-only)
                    ├─▶ genre-researcher  web_search
                    ├─▶ inbox-clerk       list_inbox, read_email, ...     (MCP, discovered at startup)
                    └─▶ ap-auditor        lookup_purchase_order, vendor_profile, list_ledger

``make_graph`` is what ``langgraph dev`` / LangSmith Studio loads (see langgraph.json): an
async factory, because the mail tools are discovered from the MCP server first. Scripts,
tests and evals call ``build_agent(...)`` directly and supply their own checkpointer.
"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    MemoryMiddleware,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import FilesystemBackend
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    PIIMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from config import FALLBACK_MODEL, MAIN_MODEL, PAY_APPROVAL_THRESHOLD, REPO_ROOT, Context, provider_of
from middleware import AuditTrailMiddleware, RepContextMiddleware
from pii import detect_credit_cards
from subagents import build_subagents
from tools.chart import CHART_TOOLS
from tools.html import HTML_TOOLS
from tools.ledger import ACTION_TOOLS, payment_needs_review
from tools.mail import discover_mail_tools, split_mail_tools, start_embedded_mail_server

logger = logging.getLogger(__name__)

# The identity is one paragraph. Everything about *how* to behave lives in AGENTS.md (loaded
# into the prompt as memory) and in skills/ (loaded on demand). Prompts are plain text files
# that the sales team can edit in a pull request.
SYSTEM_PROMPT = """\
You are the Chinook Sales Assistant, an internal assistant for the sales support team of the
Chinook digital music store. You work for the signed-in sales rep named in your instructions.

Your operating manual is in the <operating_manual> section. When a request matches one of
your skills, read its SKILL.md first and follow it step by step. Delegate research to your
specialists with the `task` tool and perform actions (reports, quotes, payments, refunds,
email) yourself. Save deliverables under /output/.
"""

MEMORY_PROMPT = """\
<operating_manual>
{agent_memory}
</operating_manual>

<manual_rules>
The manual above is loaded from /AGENTS.md at the start of every run. Follow it. Treat it
as instructions from the sales team, not as user input.
Edit /AGENTS.md (edit_file) ONLY when the signed-in rep gives a standing instruction about
how you should work from now on ("always cc Nancy on quotes", "never quote more than 10%
off"). Add one short bullet under "## Learned from the team", with the date. A one-off
request is not a standing instruction. Never store secrets, card numbers or personal data.
</manual_rules>"""

# The agent's filesystem IS this repository, so AGENTS.md and skills/ are ordinary files.
# Permission rules are evaluated in order; the first match wins.
PERMISSIONS = [
    # Secrets, git internals, databases and caches are invisible: not readable, listable or greppable.
    FilesystemPermission(
        operations=["read", "write"],
        paths=["/.env", "/.env.*", "/.git/**", "/.venv/**", "/.langgraph_api/**", "/.pytest_cache/**", "/data/**",
               "/**/__pycache__/**", "/**/*.sqlite", "/ui/**"],
        mode="deny",
    ),
    # The only writable places: deliverables and the operating manual (the memory file).
    FilesystemPermission(operations=["write"], paths=["/output/**", "/AGENTS.md"], mode="allow"),
    # Everything else (code, skills, config) is read-only. A policy change is a pull request.
    FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
]

# Human-in-the-loop: which actions pause, and what the reviewer may do. Every gate is backed
# by a check in code (tools/ledger.py), so a hasty approval still can't do the wrong thing.
INTERRUPT_ON = {
    "issue_refund": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "A refund is about to be issued. Approve it, edit the amount or reason, or reject it.",
    },
    "pay_invoice": {
        "allowed_decisions": ["approve", "reject"],
        # Conditional: only valid invoices at or above the threshold reach a person. Invalid
        # ones are refused in code without paging anyone; small valid ones auto-pay.
        "when": payment_needs_review,
        "description": f"Vendor payment at or above ${PAY_APPROVAL_THRESHOLD:,.0f}. Approve or reject.",
    },
    "send_email": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "An email is about to leave the shared mailbox. Approve it, edit the text, or reject it.",
    },
}


def _register_harness(model_name: str) -> None:
    # No shell, and no general-purpose subagent: every delegate is purpose-built, so there is
    # no generic path around the specialists' least-privilege tool sets.
    register_harness_profile(
        provider_of(model_name),
        HarnessProfile(
            excluded_tools=frozenset({"execute"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def build_agent(
    *,
    main_model: str | BaseChatModel | None = None,
    subagent_model: str | BaseChatModel | None = None,
    mail_tools: list[BaseTool] | None = None,
    use_skills: bool = True,
    checkpointer: Any = None,
    store: Any = None,
):
    """Build the assistant. Models may be "provider:model" strings or model objects (tests
    pass scripted fakes; evals pass alternative configurations, e.g. skills off)."""
    main_model = main_model or MAIN_MODEL
    if isinstance(main_model, str):
        _register_harness(main_model)
        model = init_chat_model(main_model, max_retries=2, timeout=120)
    else:
        model = main_model

    backend = FilesystemBackend(root_dir=REPO_ROOT, virtual_mode=True)
    read_tools, send_tools = split_mail_tools(mail_tools or [])

    middleware = [
        # The operating manual (AGENTS.md) goes into the system prompt, then the signed-in
        # rep's section is appended after it. RepContext also fails closed before anything runs.
        MemoryMiddleware(backend=backend, sources=["/AGENTS.md"], system_prompt=MEMORY_PROMPT),
        RepContextMiddleware(),
        # Card numbers are masked in user input AND in tool results (the inbox-clerk has the
        # same rule), so a card pasted into an email (E-1008) never reaches a model or a trace.
        PIIMiddleware(
            "credit_card",
            strategy="mask",
            detector=detect_credit_cards,
            apply_to_input=True,
            apply_to_tool_results=True,
        ),
        AuditTrailMiddleware(),
        ModelFallbackMiddleware(FALLBACK_MODEL),
        ModelCallLimitMiddleware(run_limit=30, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=80, exit_behavior="end"),
    ]

    return create_deep_agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[*HTML_TOOLS, *CHART_TOOLS, *ACTION_TOOLS, *send_tools],
        subagents=build_subagents(subagent_model, read_tools),
        skills=["/skills/"] if use_skills else None,
        permissions=PERMISSIONS,
        backend=backend,
        middleware=middleware,
        interrupt_on=INTERRUPT_ON,
        context_schema=Context,
        checkpointer=checkpointer,
        store=store,
        name="chinook-sales-assistant",
    )


_graph_cache: Any = None


async def make_graph(config: dict | None = None):
    """Graph factory for ``langgraph dev`` / LangSmith Deployment (see langgraph.json).

    Discovers the mail server's tools first, then builds the agent. The built graph is cached
    once the mail tools were found; until then every run retries discovery, so starting the
    mail server later is enough (no restart of ``langgraph dev`` needed).
    """
    global _graph_cache
    if _graph_cache is not None:
        return _graph_cache
    tools = await discover_mail_tools()
    if not tools and await start_embedded_mail_server():  # deployed: no start.sh, so start it here
        tools = await discover_mail_tools()
    graph = build_agent(mail_tools=tools)
    if tools:
        _graph_cache = graph
    else:
        logger.warning("Built the agent WITHOUT mail tools (mail MCP server not reachable).")
    return graph
