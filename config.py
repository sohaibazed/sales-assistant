"""Configuration: models, paths, and the run-scoped Context (who is signed in).

Every model is a ``"provider:model"`` string resolved by ``init_chat_model``, so switching
vendors (OpenAI -> Anthropic -> Bedrock -> a local model) is a config change, not a code
change. That is the "no lock-in" point of the LangChain model layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent
load_dotenv(REPO_ROOT / ".env")

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR = REPO_ROOT / "data"
CHINOOK_DB = DATA_DIR / "chinook.db"  # the sales database (ships with the agent)
LEDGER_DB = DATA_DIR / "ledger.sqlite"  # the agent's ONLY write path (payments, refunds, audit)
SKILLS_DIR = REPO_ROOT / "skills"
OUTPUT_DIR = REPO_ROOT / "output"  # HTML/PNG deliverables land here

# ── Models ────────────────────────────────────────────────────────────────────
_HAS_OPENAI = bool(os.getenv("OPENAI_API_KEY"))
# MAIN: plans, delegates, writes deliverables, performs the gated actions.
MAIN_MODEL = os.getenv("MAIN_MODEL") or ("openai:gpt-5.4" if _HAS_OPENAI else "anthropic:claude-sonnet-4-6")
# SUBAGENT: the four specialists do narrow tool work, so a fast, cheap model is enough.
SUBAGENT_MODEL = os.getenv("SUBAGENT_MODEL") or ("openai:gpt-4.1-mini" if _HAS_OPENAI else "anthropic:claude-haiku-4-5")
# FALLBACK: used automatically when the main model errors (outage, rate limit).
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL") or SUBAGENT_MODEL
# JUDGE: LLM-as-judge for evals. Prefer a model that differs from the agent's (self-preference bias).
JUDGE_MODEL = os.getenv("JUDGE_MODEL") or ("openai:gpt-5.5" if _HAS_OPENAI else "anthropic:claude-sonnet-4-6")

# ── Integrations ──────────────────────────────────────────────────────────────
MAIL_MCP_URL = os.getenv("MAIL_MCP_URL", "http://127.0.0.1:8765/mcp")
# The pandas data specialist (data_agent/) runs as its own deployment; unset = not wired in.
DATA_AGENT_URL = os.getenv("DATA_AGENT_URL", "")
DATA_AGENT_GRAPH_ID = os.getenv("DATA_AGENT_GRAPH_ID", "data_agent")
# Vendor invoices at or above this amount pause for a human before payment.
PAY_APPROVAL_THRESHOLD = float(os.getenv("PAY_APPROVAL_THRESHOLD", "1000"))


def provider_of(model_name: str) -> str:
    """'openai:gpt-5.4' -> 'openai'."""
    return model_name.split(":", 1)[0] if ":" in model_name else model_name


# ── Login (auth.py, webapp.py) ────────────────────────────────────────────────
# Demo users live in .env as AUTH_USERS="jane:<password>:3,margaret:<password>:4,...". The
# Agent Server signs a token with AUTH_SECRET at login and checks it on every API request.
AUTH_SECRET = os.getenv("AUTH_SECRET", "")
AUTH_TOKEN_TTL_HOURS = float(os.getenv("AUTH_TOKEN_TTL_HOURS", "8"))


@dataclass(frozen=True)
class DemoUser:
    username: str
    password: str
    rep_id: int


def parse_auth_users(raw: str) -> dict[str, DemoUser]:
    """'jane:pw:3,margaret:pw:4' -> {"jane": DemoUser("jane", "pw", 3), ...}. Raises ValueError."""
    users: dict[str, DemoUser] = {}
    for entry in filter(None, (e.strip() for e in raw.split(","))):
        parts = entry.split(":")
        if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2].isdigit():
            raise ValueError(f"AUTH_USERS entry {parts[0] or entry!r} must look like username:password:rep_id")
        username = parts[0].strip().lower()
        users[username] = DemoUser(username, parts[1], int(parts[2]))
    return users


def auth_users() -> dict[str, DemoUser]:
    return parse_auth_users(os.getenv("AUTH_USERS", ""))


# ── Run-scoped context: the trust boundary ────────────────────────────────────
@dataclass
class Context:
    """Who is using the assistant. Set by the application, never by the model.

    ``rep_id`` is the Chinook ``Employee.EmployeeId`` of the signed-in sales support agent
    (3 = Jane Peacock, 4 = Margaret Park, 5 = Steve Johnson). It scopes territory reports,
    signs outgoing mail and is written to the audit trail with every gated action.
    Behind the Agent Server's login, the signed-in user's rep wins (RepContextMiddleware);
    a different ``rep_id`` here is refused. Trusted callers without a login (Studio, evals,
    scripts/chat.py, tests) set it directly, e.g. ``{"rep_id": 3}``.
    """

    rep_id: int | None = None
