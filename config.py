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
# Vendor invoices at or above this amount pause for a human before payment.
PAY_APPROVAL_THRESHOLD = float(os.getenv("PAY_APPROVAL_THRESHOLD", "1000"))


def provider_of(model_name: str) -> str:
    """'openai:gpt-5.4' -> 'openai'."""
    return model_name.split(":", 1)[0] if ":" in model_name else model_name


# ── Run-scoped context: the trust boundary ────────────────────────────────────
@dataclass
class Context:
    """Who is using the assistant. Set by the application after login, never by the model.

    ``rep_id`` is the Chinook ``Employee.EmployeeId`` of the signed-in sales support agent
    (3 = Jane Peacock, 4 = Margaret Park, 5 = Steve Johnson). It scopes territory reports,
    signs outgoing mail and is written to the audit trail with every gated action.
    In LangSmith Studio, set the run context to ``{"rep_id": 3}``.
    """

    rep_id: int | None = None
