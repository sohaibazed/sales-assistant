"""Newsletter writer: builds the weekly newsletter end to end, deployed as its own graph.

It runs on its own Agent Server (start.sh, port NEWSLETTER_AGENT_PORT) and the main agent
reaches it as an async subagent: the rep starts it, keeps working, and the HTML file lands
in output/ when it is done. It reuses the main project's tools (installed in the same venv)
so the read-only SQL guards and the HTML template stay in one place.

The playbook is skills/weekly-newsletter/SKILL.md, the same file the main agent uses when
this server is not wired in, so the newsletter policy has one source of truth.
"""

from __future__ import annotations

import os

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware

from config import MAIN_MODEL, SKILLS_DIR
from tools.html import HTML_TOOLS
from tools.search import SEARCH_TOOLS
from tools.sql import SQL_TOOLS

MODEL = os.getenv("NEWSLETTER_AGENT_MODEL") or MAIN_MODEL

PLAYBOOK = (SKILLS_DIR / "weekly-newsletter" / "SKILL.md").read_text(encoding="utf-8")

SYSTEM_PROMPT = f"""\
You are the newsletter-writer for the Chinook digital music store. You produce the weekly
customer newsletter on your own, start to finish, and save it as an HTML file.

Follow the playbook below with these substitutions:
- Skip section 0 (that is for the main assistant, which delegates to you).
- Where it says to ask the chinook-analyst, run the SQL yourself with run_sql
  (describe_schema first if unsure of a column). Every figure must come from a query.
- Where it says to ask the genre-researcher, use web_search yourself.
- Do not send email; you have no mail tools.

When done, reply with the file path and the three headline facts.

<playbook>
{PLAYBOOK}
</playbook>
"""

graph = create_agent(
    MODEL,
    tools=[*SQL_TOOLS, *SEARCH_TOOLS, *HTML_TOOLS],
    system_prompt=SYSTEM_PROMPT,
    middleware=[ModelCallLimitMiddleware(run_limit=25, exit_behavior="end")],
    name="newsletter-writer",
)
