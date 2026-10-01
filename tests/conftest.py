"""Offline test fixtures: scripted chat models, a live mail MCP server on a test port and a
private ledger per test. No API keys, no network beyond localhost, a few seconds per run."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Model objects are constructed at import time; offline tests never call them.
os.environ.setdefault("OPENAI_API_KEY", "offline-test")
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["MAIL_MCP_PORT"] = "8790"
os.environ["MAIL_MCP_URL"] = "http://127.0.0.1:8790/mcp"
# Login settings for auth.py / webapp.py tests (never the real .env values).
os.environ["AUTH_SECRET"] = "offline-test-secret-offline-test-secret"
os.environ["AUTH_USERS"] = "jane:jane-pw:3,margaret:margaret-pw:4,ghost:ghost-pw:999"

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402


class ScriptedModel(FakeMessagesListChatModel):
    """Replays a fixed list of AIMessages and records every prompt it receives."""

    prompts: list = []

    def bind_tools(self, tools, **kwargs):  # tools are irrelevant to a scripted model
        return self

    def _generate(self, messages, *args, **kwargs):
        self.prompts.append(messages)
        return super()._generate(messages, *args, **kwargs)


def call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def scripted(*responses) -> ScriptedModel:
    msgs = [r if isinstance(r, AIMessage) else AIMessage(content=r) for r in responses]
    return ScriptedModel(responses=msgs, prompts=[])


def run(coro):
    """Run a coroutine from a sync test (the agent is async because MCP tools are)."""
    return asyncio.run(coro)


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def mail_server():
    """The fake mail MCP server, on a test port, for the whole session."""
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "mcp" / "mail_server.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "MAIL_MCP_PORT": "8790"},
    )
    for _ in range(50):
        if _port_open(8790):
            break
        time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("mail server did not start")
    yield proc
    proc.terminate()


@pytest.fixture(scope="session")
def mail_tools(mail_server):
    from tools.mail import discover_mail_tools_sync

    tools = discover_mail_tools_sync(refresh=True)
    assert tools, "no mail tools discovered"
    return tools


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path):
    """Each test gets its own ledger (payments, refunds, audit trail)."""
    from tools.ledger import isolated_ledger as _isolated

    with _isolated(tmp_path / "ledger.sqlite"):
        yield
