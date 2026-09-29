"""Discover the mail MCP server's tools at startup (langchain-mcp-adapters).

The agent has no mail code of its own. It connects to ``MAIL_MCP_URL``, asks the server
what it can do, and hands the tools out:

* read tools (list_inbox, read_email, search_inbox, mark_processed, list_sent)
  -> the ``inbox-clerk`` subagent, so untrusted email content lands in a specialist's
     context window, not the main agent's;
* ``send_email`` -> the main agent, gated by a human (approve / edit / reject).

MCP tools are async, so the agent is invoked with ``ainvoke`` / ``astream`` (which is how
``langgraph dev`` and LangSmith Deployment run it anyway).
"""

from __future__ import annotations

import asyncio
import logging
import threading

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from config import MAIL_MCP_URL

logger = logging.getLogger(__name__)

READ_TOOL_NAMES = {"list_inbox", "read_email", "search_inbox", "mark_processed", "list_sent"}
SEND_TOOL_NAMES = {"send_email"}
# Anything else the server exposes (e.g. reset_mailbox) is never handed to an agent.

_cache: list[BaseTool] | None = None


def mail_client() -> MultiServerMCPClient:
    return MultiServerMCPClient({"mail": {"url": MAIL_MCP_URL, "transport": "streamable_http"}})


async def discover_mail_tools(*, refresh: bool = False) -> list[BaseTool]:
    """Fetch the mail server's tools (cached after the first successful discovery).

    If the server isn't running, log a warning and return no tools: the agent still starts,
    just without mail. The next build retries, so starting the server later is enough.
    """
    global _cache
    if _cache is not None and not refresh:
        return _cache
    try:
        tools = await mail_client().get_tools()
    except Exception as e:  # noqa: BLE001 - connection errors of every flavor
        logger.warning("Mail MCP server not reachable at %s (%s). Start it with: python mcp/mail_server.py", MAIL_MCP_URL, e)
        return []
    logger.info("Discovered %d mail tools from %s: %s", len(tools), MAIL_MCP_URL, [t.name for t in tools])
    _cache = tools
    return tools


def discover_mail_tools_sync(*, refresh: bool = False) -> list[BaseTool]:
    """Same, for synchronous callers (scripts, tests). Safe to call inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(discover_mail_tools(refresh=refresh))
    result: list[BaseTool] = []

    def runner() -> None:
        result.extend(asyncio.run(discover_mail_tools(refresh=refresh)))

    t = threading.Thread(target=runner)
    t.start()
    t.join()
    return result


def split_mail_tools(tools: list[BaseTool]) -> tuple[list[BaseTool], list[BaseTool]]:
    """(read tools for the inbox-clerk, send tools for the main agent)."""
    read = [t for t in tools if t.name in READ_TOOL_NAMES]
    send = [t for t in tools if t.name in SEND_TOOL_NAMES]
    return read, send


async def reset_mailbox(tools: list[BaseTool]) -> None:
    """Eval helper: put the mailbox back to its seeded state (sent mail and processed flags)."""
    tool = next((t for t in tools if t.name == "reset_mailbox"), None)
    if tool is not None:
        await tool.ainvoke({})
