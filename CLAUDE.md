# CLAUDE.md — Chinook Sales Assistant

Project memory for Claude Code. Read this first; it captures everything built so far, why,
what is verified, and what is not.

## 1. What this is and why it exists

- An interview demo for a **Deployed Engineer role at LangChain**. Sohaib's second technical
  demo with Kevin Frank (Deployed Engineer Manager) is **Friday Oct 2, 2026**. Kevin's
  feedback on round 1: strong at selling, technical demo not covered in detail. He wants a
  detailed demo of LangChain OSS (LangChain, LangGraph, Deep Agents) and why companies should
  choose LangChain / LangGraph / LangSmith, **including evals**. Sohaib also wants to show
  agents, deep agents, subagents, middleware, context engineering and LangSmith features.
- The repo follows the LangChain Academy "Lesson 3: The Sales Assistant" layout
  (`agent.py`, `langgraph.json`, `start.sh`, `AGENTS.md`, `skills/`, `subagents.py`, `tools/`,
  `mcp/`, `data/chinook.db`) plus `evals/`, `tests/`, `scripts/`, `config.py`, `middleware.py`.
- Reference implementation from round 2: `~/Desktop/interview-prep/asme-agent-demo`
  (branch `demo-v2`, the "Chinook Concierge": customer support bot, deep agent + 2
  specialists, skills, per-customer memory, guardrail middleware, HITL refunds, eval suite).
  Its runbook and Q&A drill live in `~/Desktop/interview-prep/demo-v2-prep/` and in the
  claude.ai project "Langchain Interview Prep" (`claude/round2-demo-runbook.md`,
  `claude/round2-qa-drill.md`). Kevin has seen that demo; this repo is the new one.
- The demo runbook for this repo is `DEMO.md` (also saved to the claude.ai project as
  `claude/sales-assistant-demo-runbook.md`). `README.md` is the public-facing overview.

## 2. The business story

A sales support desk at Chinook (digital music store) gets mail all day. The assistant
(signed in as a sales rep) reads the shared mailbox through an **MCP server**, researches
with **read-only SQL**, writes **HTML deliverables** (quotes, newsletters, territory
reports), and takes real actions (**pay vendor invoices, issue refunds, send email**) with a
**person approving** anything with a side effect. Four outcomes from one prompt ("Process all
the vendor invoices in the inbox"): one auto-pays, one pauses for approval, one is refused in
code, one is flagged as fraud.

## 3. Stack (installed and verified in a Python 3.11 venv; Sohaib's Mac used 3.12 in round 2)

| Package | Version | Notes |
|---|---|---|
| deepagents | 0.7.20 | `create_deep_agent(model, tools, system_prompt, middleware, subagents, skills, memory, permissions, backend, interrupt_on, context_schema, checkpointer, store, name)` |
| langchain | 1.4.3 | middleware: `AgentMiddleware`, `HumanInTheLoopMiddleware`, `InterruptOnConfig` (`allowed_decisions`, `description`, `args_schema`, `when`), `PIIMiddleware`, `ModelFallbackMiddleware`, `ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`, `ToolRetryMiddleware` |
| langgraph | 1.2.12 | |
| langsmith | 0.14.1 | `aevaluate` (async target), `langsmith.testing`, pytest plugin |
| openevals | 0.2.0 | `create_llm_as_judge`, `create_trajectory_llm_as_judge`, simulators |
| langchain-mcp-adapters | 0.3.2 | pins **mcp<2**; tools are **async-only** (`ainvoke`) |
| mcp | 1.30.0 | `mcp.server.fastmcp.FastMCP(name, host=, port=, stateless_http=True)`; `run(transport="streamable-http")` |
| langgraph-cli[inmem] | 0.4.32 / langgraph-api 0.15.1 | `langgraph dev`; supports **async graph factories** (coroutine awaited) |
| matplotlib, python-dotenv, pytest | | |

Install: `python3 -m venv .venv && source .venv/bin/activate && pip install -e .`
(Debian's system pip + `forbiddenfruit` fails to build outside a venv; always use a venv.)

## 4. Layout and responsibilities

```
agent.py          build_agent(...) + async make_graph(config) factory for langgraph.json. SYSTEM_PROMPT (short identity),
                  MEMORY_PROMPT (wraps AGENTS.md, strict write rules), PERMISSIONS, INTERRUPT_ON, middleware list.
config.py         REPO_ROOT, DATA_DIR, CHINOOK_DB, LEDGER_DB, SKILLS_DIR, OUTPUT_DIR; MAIN/SUBAGENT/FALLBACK/JUDGE models
                  ("provider:model" strings, OpenAI defaults when OPENAI_API_KEY is set); MAIL_MCP_URL; PAY_APPROVAL_THRESHOLD;
                  dataclass Context(rep_id) = the run-scoped trust boundary.
middleware.py     RepContextMiddleware (before_agent fails closed; wrap_model_call appends "## Signed-in user" section),
                  AuditTrailMiddleware (wrap_tool_call → ledger audit_log for pay_invoice/issue_refund/send_email).
subagents.py      four SubAgent specs: chinook-analyst (SQL_TOOLS), genre-researcher (SEARCH_TOOLS),
                  inbox-clerk (MCP read tools + its own PIIMiddleware), ap-auditor (AP_LOOKUP_TOOLS). Cheap model, call limits.
AGENTS.md         operating manual; loaded into the prompt by MemoryMiddleware; the ONLY memory file; agent may edit it
                  (standing instructions only, under "## Learned from the team"). Reset with `git checkout -- AGENTS.md`.
skills/*/SKILL.md rfq-quote, weekly-newsletter, territory-report, invoice-processing, refund-policy (YAML frontmatter
                  name+description; progressive disclosure). Business policy lives here (discount table, refund rules).
tools/sql.py      query()/query_one() helpers (read-only `mode=ro` connection), describe_schema, run_sql (single SELECT,
                  50-row cap with true total in the header).
tools/ledger.py   ledger.sqlite (purchase_orders + vendors seeded, vendor_payments, refunds, audit_log). validate_payment(),
                  payment_needs_review() (the `when` predicate), po_remaining(), tools: lookup_purchase_order, vendor_profile,
                  list_ledger (auditor) and pay_invoice, issue_refund (main agent, gated). isolated_ledger() is a ContextVar.
tools/html.py     write_html_report(filename, title, subtitle, body_markdown) → output/<name>.html (small Markdown subset:
                  headings, paragraphs, bullets, pipe tables, ![img](file.png)); branded template in code.
tools/chart.py    render_bar_chart(filename, title, labels, values, value_label) → output/<name>.png (matplotlib Agg).
tools/search.py   web_search: Tavily if TAVILY_API_KEY (optional dep langchain-tavily) else OFFLINE_NOTES corpus, says which.
tools/mail.py     discover_mail_tools() (async, cached after first success), discover_mail_tools_sync(), split_mail_tools()
                  (READ_TOOL_NAMES → clerk, SEND_TOOL_NAMES → main), reset_mailbox() (evals only).
mcp/mail_server.py FastMCP "chinook-mail" on 127.0.0.1:8765 (/mcp), stateless. 11 seeded messages E-1001..E-1011, SENT,
                  PROCESSED in memory. Tools: list_inbox, read_email, search_inbox, mark_processed, send_email, list_sent,
                  reset_mailbox (never given to an agent). **No __init__.py in mcp/** (would shadow the mcp package).
data/chinook.db   copied from asme-agent-demo/data/Chinook_Sqlite.sqlite (lerocha version; invoice dates 2021-2025).
evals/            examples.py (20 examples, DB-computed references, stable uuid5 ids, splits smoke/full), dataset.py (sync),
                  evaluators.py (code checks, openevals judges, trajectory judge, action_safety summary), target.py (async
                  runner: auto-approve pauses, reset mailbox, isolated ledger, deliverable snapshot), run_experiment.py
                  (aevaluate; --variant full|no-skills, --split, --examples, --reps, --concurrency default 1, --prefix,
                  --main-model, --subagent-model), simulate.py (vendor bank-change social engineering, openevals
                  simulators), test_live.py (@pytest.mark.langsmith).
tests/            conftest.py (ScriptedModel, mail server fixture on port 8790, isolated ledger), test_wiring.py (26),
                  test_evals.py (3). 29 pass in ~10s, no API keys.
scripts/chat.py   terminal chat with approve/edit/reject prompts (Studio fallback).
scripts/create_assistants.py  one assistant per rep with default context {"rep_id": n} (for Agent Chat UI etc.).
start.sh          starts mail server, waits for it, `exec langgraph dev`; `--reset` wipes ledger, .langgraph_api, AGENTS.md.
langgraph.json    {"graphs": {"sales_assistant": "./agent.py:make_graph"}, "env": ".env"}
```

## 5. Design decisions (the "why", for the demo and for future changes)

1. **Identity is context, never a tool argument.** `Context.rep_id` (Employee 3 Jane Peacock,
   4 Margaret Park, 5 Steve Johnson) is set by the app (Studio context panel or an assistant's
   default context). `RepContextMiddleware` raises `PermissionError` without it. Clients that
   can't set context (Agent Chat UI) use per-rep assistants (`scripts/create_assistants.py`);
   verified: assistant context reaches the run, bare graph id fails closed.
2. **The repo is the agent's filesystem** (`FilesystemBackend(root_dir=REPO_ROOT, virtual_mode=True)`).
   Permission rules (first match wins): deny read+write on `/.env`, `/.env.*`, `/.git/**`,
   `/.venv/**`, `/.langgraph_api/**`, `/.pytest_cache/**`, `/data/**`, `/**/__pycache__/**`,
   `/**/*.sqlite`; allow write on `/output/**` and `/AGENTS.md`; deny write on `/**`.
   Verified: `.env` invisible to read_file, ls, glob and grep; code and skills read-only.
3. **Skills = plain-text playbooks, versioned in git**; only names/descriptions in the prompt.
   `use_skills=False` builds the same agent without them (the A/B experiment variant).
4. **Specialists for context isolation and least privilege.** Untrusted email is read only by
   the inbox-clerk (which also masks card numbers via its own PIIMiddleware) and reported as
   data; the clerk cannot send; nothing side-effecting lives on a specialist. General-purpose
   subagent and `execute` disabled via `register_harness_profile(provider, HarnessProfile(...))`.
5. **Three approval gates, each backed by code** (`INTERRUPT_ON` in agent.py):
   `issue_refund` always (approve/edit/reject; tool re-validates invoice + amount ≤ total −
   prior refunds); `pay_invoice` conditional via `when=payment_needs_review` (pauses only if
   valid AND amount ≥ PAY_APPROVAL_THRESHOLD=1000; invalid → refused in code, no interrupt;
   small valid → auto-pay; approve/reject only); `send_email` (MCP tool; approve/edit/reject).
   Resume format: `Command(resume={"decisions": [{"type": "approve"} | {"type": "reject",
   "message": ...} | {"type": "edit", "edited_action": {"name", "args"}}]})`. Interrupt payload:
   `interrupt.value["action_requests"]` + `["review_configs"]`.
6. **The ledger is the only write path**; Chinook DB is opened read-only at the driver level.
   Duplicate invoice numbers, wrong-vendor POs, over-balance amounts are refused in code.
7. **MCP discovery at startup** via an async graph factory (`make_graph`); the graph is cached
   only once discovery succeeds, so starting the mail server late needs no restart. Without the
   server the agent still builds (no mail tools) and logs a warning. MCP tools are async-only,
   so everything runs with `ainvoke`/`astream` (evals use `aevaluate`).
8. **Memory = AGENTS.md** with a custom `MEMORY_PROMPT` (write only for standing instructions).
   MemoryMiddleware is listed *before* RepContextMiddleware so the manual precedes the
   "Signed-in user" section in the prompt.
9. **Models are config.** Defaults with an OpenAI key: main `openai:gpt-5.4`, specialists/fallback
   `openai:gpt-4.1-mini`, judge `openai:gpt-5.5` (same models that ran in round 2; Sohaib's
   Anthropic key was rejected/401 in round 2, so don't rely on Anthropic live).
10. **Evals check state, not just text**: `ledger_state`, `approval_gate`, `deliverable`,
    `no_secret_leak` (env key values, never stored in the dataset), `fraud_flagged`, plus
    `tool_routing`, `no_forbidden_content`; judges get app context ("judges must see what the
    agent saw"); `SKIP = {"results": []}` for not-applicable. Mailbox and `output/` are shared
    state → `--concurrency 1` by default; target resets the mailbox per example.

## 6. Seed data you'll need to reason about

- Reps: Employee 3 Jane Peacock (21 customers; top 2025 country Canada $39.60; territory 2025
  $156.43 vs 2024 $146.60), 4 Margaret Park, 5 Steve Johnson; Sales Manager Nancy Edwards (2).
- Customers used: 1 Luís Gonçalves (Embraer, Brazil, rep 3; invoice 98 = $3.98, two episodes
  "Experiment In Terra"/"Take the Celestra", 2022-03-11); 16 Frank Harris (Google Inc., USA,
  rep 4, 7 invoices $37.62); 38 Niklas Schröder (Germany, rep 3; invoice 236 = $13.86, 2023);
  26 Richard Cunningham (E-1008 card number).
- 2025 totals: revenue $450.58 / 80 invoices; top genre Rock $174.24, then Latin $79.20.
  Catalog: Jazz 130 tracks, Bossa Nova **15** (the RFQ asks for 20 → shortfall filled from Latin
  per the rfq-quote skill), Latin 579. Unit price $0.99 (episodes $1.99).
- Purchase orders (tools/ledger.py): PO-1042 Northwind Music Licensing $4,800; PO-1051
  CloudStack Hosting $349; PO-1060 Apex Studio Rentals $1,200; PO-1063 Brightline Design $850.
  Vendors on file with bank last-4 (Northwind ****7781) and email domains (northwindlicensing.com).
- Inbox: E-1001 Northwind invoice NWL-2026-0912 $4,800 PO-1042 (→ pauses); E-1002 CloudStack
  CS-77213 $349 PO-1051 (→ auto-pays); E-1003 Apex APX-2026-118 $2,150 PO-1060 (→ refused,
  exceeds PO); E-1004 fraud: lookalike domain northwind-licensing-pay.com, "new account ending
  5533", prompt-injection text; E-1005 RFQ from fharris@google.com (20 Jazz + 20 Bossa Nova);
  E-1006 refund invoice 98 (qualifies); E-1007 refund invoice 236 change of mind (declined by
  policy); E-1008 card 4111 1111 1111 1111 (masked); E-1009 Nancy: Latin newsletter; E-1010
  team lunch; E-1011 Nancy: territory report.
- RFQ pricing per skill: 40 tracks → 10% (25-49) + 5% returning = 15%: list $39.60, total $33.66.

## 7. Commands

```bash
pytest                                           # 29 offline tests, ~10s, no keys
./start.sh [--reset]                             # mail server + langgraph dev (Studio: graph sales_assistant, context {"rep_id": 3})
python mcp/mail_server.py                        # mail server alone (port MAIL_MCP_PORT, default 8765)
python scripts/create_assistants.py [--url ...]  # per-rep assistants (Agent Chat UI: use Jane's id, not the graph name)
python scripts/chat.py --rep 3                   # terminal chat with approval prompts
python -m evals.target "Pay the CloudStack invoice CS-77213 for $349 against PO-1051"   # one run as JSON
python -m evals.dataset                          # create/update dataset sales-assistant-golden in LangSmith
python -m evals.run_experiment [--prefix baseline --reps 2] [--variant no-skills] [--split smoke --no-judges] [--examples k1,k2]
python -m evals.simulate                         # multi-turn fraud simulation
LANGSMITH_TEST_SUITE=sales-assistant-ci pytest evals/test_live.py --langsmith-output
```

## 8. What is verified vs. not

Verified (in a cloud sandbox with scripted fake models, no real LLM calls):
- 29 offline tests: identity fails closed; prompt assembly (manual → skills list → rep section);
  permissions; AGENTS.md learning across threads; refund pause/approve/reject/edit + code
  validation after approval; payment small/large/invalid/duplicate; MCP tool split; send_email
  pause + reviewer edit; card masking inside the clerk; audit trail; SQL guards; HTML/chart tools;
  dataset determinism; evaluators; async target end to end.
- `langgraph dev` loads the async factory, serves graph `sales_assistant`, exposes the
  `rep_id` context schema, discovers all 6 mail tools (first load ~300 ms, then cached).
- Per-rep assistants carry context into runs.

NOT verified (do this first on the Mac):
- **No run with real models yet.** Every prompt in DEMO.md §1 must be run at least twice.
  Likely tuning: skill wording, specialist prompts, tool descriptions, whether the agent reads
  SKILL.md first, whether it mentions the Bossa Nova shortfall, whether the quote table has
  40 rows, todo usage, over-long answers.
- `evals/dataset.py` and `run_experiment.py` against a live LangSmith workspace (code paths
  mirror round 2's working scripts; `aevaluate` signature checked).
- Agent Chat UI rendering of the HITL interrupt card (unknown; Studio and scripts/chat.py work).
- Tavily search (optional; offline corpus is the default).

## 9. Gotchas

- `mcp/` must never get an `__init__.py` (it would shadow the `mcp` PyPI package).
- MCP tools raise on sync `invoke`; use `ainvoke`. MCP tool results arrive as content blocks
  (list of `{"type": "text", ...}`), which the model handles fine; tests use `msg.text`.
- `mcp` is pinned `<2` by langchain-mcp-adapters; FastMCP import path is `mcp.server.fastmcp`.
- The mail server answers plain GET with HTTP 406 (needs MCP Accept headers); `curl -s -o
  /dev/null URL` still exits 0, which is what start.sh's readiness loop relies on.
- Paying the same invoice twice → "already paid" by design; `./start.sh --reset` clears it.
  Reset also runs `git checkout -- AGENTS.md`.
- `.env.example` is hidden from the agent too (`/.env.*` rule); harmless.
- On Sohaib's Mac `.env` was seeded from round 2's `.env` (same variable names: MAIN_MODEL,
  SUBAGENT_MODEL, FALLBACK_MODEL, JUDGE_MODEL; GUARDRAIL_MODEL/MODEL_NAME are ignored here)
  with LANGSMITH_PROJECT=sales-assistant, MAIL_MCP_URL and PAY_APPROVAL_THRESHOLD appended.
  Never print key values.
- Port 2024 was busy only in the cloud sandbox; on the Mac `langgraph dev` uses 2024.
- The first git commits were made from the Cowork VM, which cannot delete files; stale
  `.git/*.lock` and `tmp_obj_*` files were cleaned afterwards (`git fsck` clean). If a commit
  ever fails with "HEAD.lock exists", delete `.git/HEAD.lock`.

## 10. Conventions for changes

- Business policy goes in `skills/` or `AGENTS.md`, not in Python prompts; wiring goes in
  `agent.py`; every new gated tool gets a code-level validation and an offline test.
- Tests use scripted models (`tests/conftest.py: scripted(), call()`), never real keys.
- Every new capability gets a dataset example (`evals/examples.py`, stable key) and, if it
  changes state, a `ledger`/`deliverable` expectation.
- Keep tool results honest for a model reader: say when truncated, include ids the next
  step needs, refuse with a reason.
- Commit messages: imperative, one line; the repo is on `main`, two commits so far
  (`18dd5fa` initial, `74849a5` assistants).

## 11. Open work before Friday Oct 2

1. `pip install -e .`, `pytest`, `./start.sh`; run DEMO.md §1 prompts twice; fix and note
   every issue (the "friction log" and the improvement-loop story).
2. `python -m evals.dataset`; `run_experiment --prefix baseline --reps 2`; fix top issues;
   `--prefix fixed`; `--variant no-skills` for the A/B compare view.
3. In LangSmith UI: annotation queue "assistant-review", online evaluator on project
   `sales-assistant`, automation rule → queue; try the Align Evaluator on the correctness judge.
4. Rehearse with a timer (45 min: ~38 demo + Q&A); fill in the numbers in DEMO.md §1F.
5. Optional: multi-turn `evals.simulate`, `evals/test_live.py` suite, Agent Chat UI check.
