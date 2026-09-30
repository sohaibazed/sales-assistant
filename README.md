# Chinook Sales Assistant

An internal assistant for the sales support team of the Chinook digital music store, built
with **LangChain OSS** (`create_deep_agent`, middleware, the **LangGraph** runtime) and
observed and evaluated in **LangSmith**. It reads a shared mailbox through an **MCP** server,
answers with read-only SQL, writes quotes, newsletters and territory reports as HTML, and
pays vendor invoices, issues refunds and sends email, with a **person approving** anything
that has a side effect.

```
sales_assistant/
├── agent.py            # assembles the agent, the only "wiring" code (create_deep_agent)
├── config.py           # models ("provider:model"), paths, and the run Context (signed-in rep)
├── middleware.py       # custom middleware: rep context (identity + dynamic prompt), audit trail
├── subagents.py        # the four specialists
├── AGENTS.md           # operating manual: plain text, loaded into the prompt as memory
├── skills/             # one playbook per task: plain text, no code (progressive disclosure)
│   ├── rfq-quote/  weekly-newsletter/  territory-report/  invoice-processing/  refund-policy/
├── tools/              # tool code, each given to the agent that needs it
│   ├── sql.py          # → chinook-analyst (read-only SQL)
│   ├── search.py       # → genre-researcher (web search, offline fallback)
│   ├── ledger.py       # → ap-auditor (lookups) + main agent (pay_invoice ⏸, issue_refund ⏸)
│   ├── html.py         # → main agent (HTML deliverables under output/)
│   ├── chart.py        # → main agent (charts for the territory report)
│   └── mail.py         # discovers the mail MCP server's tools at startup
├── mcp/mail_server.py  # the fake mail MCP server (11 seeded messages); reset by restarting
├── data/chinook.db     # the sales database (ships with the agent); ledger.sqlite is created at runtime
├── evals/              # LangSmith: golden dataset, evaluators, experiments, simulation, live tests
├── tests/              # offline tests with scripted models (no API keys, ~10s)
├── scripts/chat.py     # terminal chat with approval prompts (Studio fallback)
├── langgraph.json      # tells `langgraph dev` which graph to serve (an async factory)
├── start.sh            # starts the mail server + langgraph dev
└── DEMO.md             # the demo runbook: flow, LangSmith features, talk track
```

## Architecture

```
sales rep (rep_id in the run context) ──▶ sales-assistant  (create_deep_agent, main model)
   middleware: memory (AGENTS.md) ▸ rep context ▸ PII (cards masked) ▸ audit trail ▸ fallback ▸ call limits
   harness:    todos ▸ files (this repo, with permission rules) ▸ skills ▸ summarization ▸ human-in-the-loop
   tools:      write_html_report ▸ render_bar_chart ▸ pay_invoice ⏸ conditional ▸ issue_refund ⏸ ▸ send_email ⏸ (MCP)
   ├─▶ chinook-analyst    run_sql, describe_schema          read-only connection, results say when truncated
   ├─▶ genre-researcher   web_search                        Tavily, or an offline corpus that says so
   ├─▶ inbox-clerk        list_inbox, read_email, ...       MCP tools, discovered at startup; cannot send
   └─▶ ap-auditor         lookup_purchase_order, vendor_profile, list_ledger
```

Design decisions, one line each (details in the file headers):

- **Identity is context, never a tool argument.** `rep_id` arrives in the run context (Studio: `{"rep_id": 3}`); `RepContextMiddleware` fails closed and adds a small dynamic prompt section.
- **The repo is the agent's filesystem.** `AGENTS.md` and `skills/` are ordinary files; permission rules make secrets invisible (even to `ls`/`grep`), code and skills read-only, and only `/output/` and `/AGENTS.md` writable.
- **Skills are versioned playbooks.** Only their names and descriptions sit in the prompt; the agent reads a `SKILL.md` when a request matches. A policy change is a pull request.
- **Specialists isolate context and privilege.** Email (untrusted content) is read by the inbox-clerk and reported as data; the analyst can query but not pay; nothing side-effecting lives on a specialist.
- **Every gate is backed by code.** Refunds always pause; payments pause only when valid *and* at or above the threshold (`InterruptOnConfig.when`); invalid invoices are refused in code without paging anyone; outgoing email can be edited by the reviewer.
- **MCP is the integration boundary.** The agent discovers the mailbox's tools at startup and hands out only the ones each agent should have (`reset_mailbox` exists on the server and is never given to an agent).
- **Evals prove it.** 20 golden examples, deterministic checks first (gates, ledger, deliverables, secrets), LLM judges for judgment calls, a trajectory judge for workflows, a multi-turn simulation, and offline tests for the wiring.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env            # add OPENAI_API_KEY (or ANTHROPIC_API_KEY) and LANGSMITH_API_KEY
pytest                          # 29 offline tests, no keys needed (~10s)
./start.sh                      # mail server + langgraph dev -> LangSmith Studio, graph "sales_assistant"
```

In Studio set the run context to `{"rep_id": 3}` (Jane Peacock; 4 = Margaret Park, 5 = Steve Johnson).
Deliverables land in `output/` (open them in a browser). `./start.sh --reset` wipes the ledger,
Studio threads and anything the agent learned into `AGENTS.md`.

**Agent Chat UI** ([agentchat.vercel.app](https://agentchat.vercel.app)) or any other client that
can't set a run context: create one assistant per rep, each with a default context, and point
the client at the assistant id instead of the graph name:

```bash
python scripts/create_assistants.py     # with ./start.sh running; prints three assistant ids
```

Deployment URL `http://localhost:2024`, Assistant / Graph ID = the id printed for Jane. Using
the bare graph id `sales_assistant` fails closed (`PermissionError`: no rep signed in), by design.

Prompts to try:

- "What's waiting in the shared inbox?"
- "Process all the vendor invoices in the inbox." (one auto-pays, one pauses for approval, one is refused, one is flagged as fraud)
- "Luís Gonçalves says the episodes on invoice 98 won't play. Refund him." (pauses; approve / edit / reject)
- "Frank Harris at Google emailed an RFQ (E-1005). Build the quote and send it." (HTML quote, then the email pauses for review)
- "Build my territory report for the pipeline review." (chart + HTML)
- "From now on, always cc Nancy on quotes over $500." (the agent edits AGENTS.md; the next thread knows)

## Evaluation

```bash
python -m evals.dataset                                  # create or update the golden dataset in LangSmith
python -m evals.run_experiment                           # experiment: the full agent on all 20 examples
python -m evals.run_experiment --variant no-skills       # A/B: the same agent without playbooks
python -m evals.run_experiment --split smoke --no-judges # fast CI subset, code checks only
python -m evals.simulate                                 # multi-turn: a vendor tries to change bank details
LANGSMITH_TEST_SUITE=sales-assistant-ci pytest evals/test_live.py --langsmith-output
```

See [`DEMO.md`](DEMO.md) for the demo flow and the LangSmith features to show.
