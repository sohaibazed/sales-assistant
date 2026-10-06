"""Data specialist: a small agent with pandas tools, deployed as its own graph.

It lives in its own project (pyproject.toml, langgraph.json) so pandas ships only with this
deployment, not with the main sales assistant. The main agent reaches it as an async
subagent (see DATA_AGENT_URL in ../config.py).
"""

from __future__ import annotations

import io
import os

import pandas as pd
from langchain.agents import create_agent
from langchain_core.tools import tool

MODEL = os.getenv("DATA_AGENT_MODEL") or (
    "openai:gpt-4.1-mini" if os.getenv("OPENAI_API_KEY") else "anthropic:claude-haiku-4-5"
)

SYSTEM_PROMPT = """\
You are the data-analyst specialist. You analyze tabular data with pandas.

- Use summarize_csv on the CSV text you are given. Report only figures the tool returned.
- If no data was provided, say so and ask for it as CSV text.
"""


@tool
def summarize_csv(csv_text: str) -> str:
    """Load CSV text into a pandas DataFrame and return its shape, column types and summary statistics."""
    try:
        df = pd.read_csv(io.StringIO(csv_text))
    except Exception as exc:  # malformed input is reported back, not raised
        return f"Could not parse CSV: {exc}"
    return (
        f"Rows: {len(df)}, columns: {len(df.columns)}\n\n"
        f"Types:\n{df.dtypes.to_string()}\n\n"
        f"Summary:\n{df.describe(include='all').to_string()}"
    )


graph = create_agent(MODEL, tools=[summarize_csv], system_prompt=SYSTEM_PROMPT, name="data-agent")
