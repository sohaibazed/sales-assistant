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
import importlib.util
import logging
import os
import socket
import threading
from urllib.parse import urlparse

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from config import MAIL_MCP_URL, REPO_ROOT

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


_embedded: threading.Thread | None = None


def _port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex((host, port)) == 0


async def start_embedded_mail_server(timeout: float = 10.0) -> bool:
    """Run mcp/mail_server.py in a background thread of this process, on MAIL_MCP_URL's port.

    For LangSmith Deployment, where start.sh doesn't run: only the Agent Server starts, so the
    graph factory brings the mail server up itself. It still speaks MCP over HTTP on
    127.0.0.1, so it's reachable only inside the container. Only for a local URL, and not
    when MAIL_MCP_EMBED=0. Returns True once the port accepts connections.
    """
    global _embedded
    url = urlparse(MAIL_MCP_URL)
    host, port = url.hostname or "127.0.0.1", url.port or 80
    if host not in ("127.0.0.1", "localhost") or os.getenv("MAIL_MCP_EMBED", "1") == "0":
        return False
    if _embedded is None or not _embedded.is_alive():
        import uvicorn

        # mcp/ has no __init__.py (it would shadow the mcp package), so load the file by path.
        spec = importlib.util.spec_from_file_location("chinook_mail_server", REPO_ROOT / "mcp" / "mail_server.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        server = uvicorn.Server(uvicorn.Config(module.mcp.streamable_http_app(), host=host, port=port, log_level="warning"))
        _embedded = threading.Thread(target=server.run, name="chinook-mail", daemon=True)
        _embedded.start()
        logger.info("Started the embedded mail MCP server at %s", MAIL_MCP_URL)
    for _ in range(int(timeout / 0.1)):
        if _port_open(host, port):
            return True
        await asyncio.sleep(0.1)
    logger.warning("Embedded mail MCP server did not come up at %s", MAIL_MCP_URL)
    return False


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
