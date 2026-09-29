# Demo runbook: the Sales Assistant (Friday Oct 2)

**What Kevin asked for:** a detailed demo of LangChain OSS and why companies should choose
LangChain, LangGraph and LangSmith, including evals. Last time the selling was strong and the
technical part was thin. This time the technical part *is* the demo.

**Your angle:** *"Last time I told the story. Today I'll open the hood: every layer of the
stack, live, and evals that prove it works."*

**Your story:** a sales support desk gets mail all day: vendor invoices, RFQs, refund requests,
and one fraud attempt. The assistant reads the mailbox through MCP, researches with SQL,
writes deliverables, and takes real actions (pay, refund, send) with a person approving.
That is exactly the "we got an agent to demo, but not to production" gap in Kevin's brief.

---

## 0. Setup

### Once (Tuesday/Wednesday)
```bash
cd ~/Desktop/langchain/sales_assistant
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
cp .env.example .env     # OPENAI_API_KEY + LANGSMITH_API_KEY; models default to gpt-5.4 / gpt-4.1-mini / gpt-5.5 judge
pytest                   # 29 passed, ~10s, no keys needed
./start.sh               # mail server + Studio
```
- **Every prompt in §1 must be run at least twice before Friday.** The wiring is tested
  offline; the *behavior* with real models is what you'll tune Wednesday. If a skill
  step is skipped or a specialist returns the wrong shape, edit the SKILL.md or the
  specialist prompt, re-run, and keep the before/after traces: that's the improvement
  loop you're demoing.
- Build the dataset and run the experiments that the compare view needs:
  ```bash
  python -m evals.dataset                                   # 20 examples, 7 in the smoke split
  python -m evals.run_experiment --prefix baseline --reps 2  # ~15-25 min, sequential (mailbox is shared state)
  python -m evals.run_experiment --variant no-skills --prefix no-skills
  ```
  Expect failures on the first baseline. Fix the top ones (skill wording, a specialist prompt,
  a tool description), re-run with `--prefix fixed`, and you have the story for §1E.
- Then, in the UI: an **annotation queue** ("assistant-review"), an **online evaluator** on
  the tracing project, and an **automation rule** (§2.5). 15 minutes, once.

### 30 minutes before: reset, then tabs in this order
```bash
./start.sh --reset        # ledger, Studio threads, and anything learned into AGENTS.md
```
1. **Studio**: graph `sales_assistant`, context `{"rep_id": 3}`. One warm-up prompt ("hi").
2. **Editor** with tabs: `agent.py` → `middleware.py` → `subagents.py` → `tools/ledger.py` →
   `skills/invoice-processing/SKILL.md` → `mcp/mail_server.py` → `evals/evaluators.py`.
3. **LangSmith tracing project** `sales-assistant`, with a pre-run "process all invoices"
   trace open in the Trajectory view.
4. **Datasets & Experiments** → `sales-assistant-golden` → the compare view
   (baseline vs fixed; full vs no-skills).
5. **Terminal** in the repo, venv active, mail server log visible.
6. Optional: the annotation queue and the online evaluator page.

---

## 1. Flow (45 min: ~38 demo, Q&A throughout)

| Min | Section | Show | Key line |
|---|---|---|---|
| 0-3 | **Frame** | README architecture block | "Four ways agents fail in production; each layer fixes one; evals prove it." |
| 3-10 | **OSS: `create_deep_agent` + middleware** | `agent.py`, `middleware.py` | "Policy lives in code, not in the prompt." |
| 10-19 | **Deep Agents: skills, specialists, memory, MCP** | live: inbox triage → RFQ quote | "Right information, right place, right time." |
| 19-25 | **LangGraph runtime: human in the loop** | live: process all invoices; refund | "A pause is a checkpoint. It can wait a day." |
| 25-38 | **LangSmith: the improvement loop** ⭐ | traces → dataset → evaluators → compare → judge calibration → live run → online | "I can prove every fix, and catch the next regression before a customer does." |
| 38-42 | **Why LangChain** | the 5 proof points | "Open where you need control, managed where you need speed." |
| 42-45 | **Close** | what I'd do with a customer next week | hand over to Q&A |

### A. Frame (3 min)
The README's architecture block. One line per layer:
- **Control** → middleware. **Complexity** → Deep Agents (skills, specialists, memory, files).
- **Durability** → the LangGraph runtime (checkpoints, interrupts). **Confidence** → LangSmith.
- "The customer in Kevin's brief has an agent that demos. What they don't have is the three
  things after that: control, durability, confidence. That's the stack."

### B. LangChain OSS: `create_deep_agent` + middleware (7 min)
1. `agent.py`, `build_agent()`. Point at each argument, top to bottom: model (a string, so
   vendor swap is config), tools, subagents, `skills=`, `permissions=`, `backend=` (the repo
   itself), `middleware=`, `interrupt_on=`, `context_schema=`.
   - *"Under the hood it's `create_agent`, which is a LangGraph graph. So every agent gets
     checkpoints, interrupts and streaming for free. Studio shows the middleware as nodes."*
2. **The middleware list** (`agent.py`). Order matters; say it:
   memory → rep context → PII → audit → fallback → call limits.
3. `middleware.py`: the hook sequence in the header. Two custom pieces:
   - `RepContextMiddleware`: `before_agent` fails closed (no `rep_id`, no agent);
     `wrap_model_call` appends a small per-rep section (name, territory, date). *Context
     engineering: identity comes from the app, never from the conversation.*
   - `AuditTrailMiddleware`: `wrap_tool_call` writes every payment, refund and email to an
     audit table with the rep and the outcome. *"Compliance asks who did what. It's a table."*
4. Built-ins you didn't write: `PIIMiddleware` (cards masked in input and tool results,
   also inside the inbox-clerk), `ModelFallbackMiddleware`, call limits, and Deep Agents'
   own: todos, filesystem, skills, memory, summarization, HITL.
5. **Live, 20 seconds**: "What does E-1008 say?" Open the trace: the card number reads
   `**** **** **** 1111` in the clerk's tool result and in the main agent's context.

### C. Deep Agents: skills, specialists, memory, MCP (9 min)
1. **Filesystem = the repo.** `ls` in the agent's world shows `AGENTS.md`, `skills/`,
   `output/`. Permission rules in `agent.py`: `.env` and `data/` invisible even to `grep`,
   code and skills read-only, `/output/` and `/AGENTS.md` writable. *"A policy change is a
   pull request, not a prompt edit in prod."*
2. **AGENTS.md** is the operating manual, loaded by `MemoryMiddleware` with our own write
   rules (`MEMORY_PROMPT`): only standing instructions get written. Live, at the end of the
   section: "From now on, always cc Nancy on quotes over $500." → it edits AGENTS.md → open
   the file → new thread: it knows. Then `git diff AGENTS.md`. *"Memory you can review."*
3. **Skills** (`skills/*/SKILL.md`): plain text playbooks. Only name + description are in
   the prompt (show it in the trace's system message); the agent reads the playbook when a
   request matches. Refund policy, discount table, report layout: all owned by the sales
   team, none of it code.
4. **Specialists** (`subagents.py`): each has its own tools, model and call limit. The
   inbox-clerk can read but not send; the analyst can query (read-only connection) but not
   pay; the ap-auditor can check a PO but not pay. *"Least privilege, and untrusted email
   content stays in the clerk's context window. The main agent gets a summary, as data."*
5. **MCP** (`mcp/mail_server.py`, `tools/mail.py`): the mailbox is an MCP server. The agent
   discovers its tools at startup (`make_graph` is an async factory) and hands them out by
   name. The server also exposes `reset_mailbox`, which no agent ever gets. *"Swap the URL
   for your Gmail/Exchange MCP server and nothing in the agent changes."*
6. **Live**: "Frank Harris at Google emailed an RFQ (E-1005). Build the quote and send it."
   While it runs, narrate: reads `rfq-quote/SKILL.md` first → `task` to inbox-clerk → `task`
   to chinook-analyst (watch the SQL) → notices the catalog only has 15 Bossa Nova tracks and
   fills from Latin, as the playbook says → `write_html_report` → `send_email` pauses.
   Click **edit**, change one line of the email, approve. Open `output/quote-google-*.html`
   in the browser. Then the trace: expand one `task` run to show the specialist's calls
   nested inside, and the **Trajectory view** for the flat path.

### D. LangGraph runtime: human in the loop (6 min)
1. **Live**: "Process all the vendor invoices in the inbox." Four outcomes from one prompt:
   - CloudStack $349: valid, under the threshold → **pays without asking**.
   - Northwind $4,800: valid, over the threshold → **pauses** (approve).
   - Apex $2,150 against a $1,200 PO → **refused in code**, no one paged.
   - The bank-details email → **flagged as fraud**, never acted on.
   Show `tools/ledger.py`: `payment_needs_review` (the `when` predicate) and
   `validate_payment`. *"The gate decides when a human is needed. The code decides what's
   allowed. A hasty approval still can't pay the wrong PO."*
2. **Live**: "Luís says the episodes on invoice 98 won't play. Refund him." → reads the refund
   skill → analyst verifies the invoice → `issue_refund` pauses → click **reject** with a
   reason → the agent tells Luís politely, nothing in the ledger. Then `list_ledger` via
   "what's in the ledger?" and the audit trail.
3. **Durability, one sentence with the interrupt panel open**: *"This pause is a checkpoint.
   The reviewer could approve tomorrow from a different service; the same `langgraph.json`
   deploys to LangSmith Deployment with persistence, the interrupt API, streaming and auth."*
4. If time: **time travel** in Studio (fork from an earlier checkpoint, edit the message,
   re-run) — 60 seconds, and it lands.

### E. LangSmith: the improvement loop (13 min) ⭐
Order matters: traces → dataset → evaluators → experiments → judge calibration → live run →
production loop. Each step answers "how do you know?"

1. **Tracing / Trajectory view (1 min).** The "process all invoices" trace: cost, latency and
   tokens per step; the specialists nested under `task`; the interrupt and the human decision
   recorded in the run. Press `T` for the Trajectory view: one readable thread across main
   agent and specialists. *"This is where every eval starts: you can't grade what you can't see."*
2. **Dataset (2 min).** `evals/examples.py`, then the dataset in LangSmith. 20 examples in 7
   categories: analytics, inbox, payments, refunds, workflows, security, out of scope. Reference
   answers are computed from the DB when the dataset is built, so the answer key can't go
   stale. Splits: `smoke` (7) runs in CI. Show one example's `outputs`: `expected_tools`,
   `expect_interrupt`, `ledger`, `deliverable`.
3. **Evaluators, cheapest first (3 min).** `evals/evaluators.py`:
   - **Code checks** for anything objective: `tool_routing`, `approval_gate` (did the right
     action pause, and nothing else), `ledger_state` (what was *actually* paid or refunded),
     `deliverable` (the HTML exists, has the table, mentions the shortfall), `no_secret_leak`
     (real key values from the environment, never stored in the dataset), `fraud_flagged`.
   - **LLM-as-judge** (openevals) only for judgment calls: `correctness` vs. the reference,
     `groundedness` vs. the tool results. *"Judges must see what the agent saw"*: the judge
     gets the app context (rep name, thresholds), or it flags "Hi Jane" as a hallucination.
   - **Trajectory judge** for workflows: was the path sensible, not just the answer.
   - **Summary evaluator** `action_safety`: one number per experiment, the share of examples
     where the ledger came out exactly right. *"That's the number a CFO asks for."*
4. **Experiments and the compare view (3 min).** Open `baseline` vs `fixed`: regressions red,
   improvements green, click a cell to land in the trace. Then `full` vs `no-skills`: *"Same
   agent, playbooks off. Look at `deliverable` and `trajectory_quality`. That's how I'd show a
   customer what a skill is worth, with numbers, not opinions."* Mention repetitions
   (`--reps 2`) for flaky behavior, and the metadata chips (model, git sha) on every run.
5. **Judge calibration: Align Evaluator (2 min).** *This is the answer to "why should I trust
   an LLM judge?"* Datasets → the dataset → Evaluators → your `correctness` judge → **Align**:
   label ~20 outputs in the annotation queue (0/1), then the evaluator playground shows the
   **alignment score** (share of examples where judge and human agree). Iterate the judge
   prompt until it agrees with your labels, then trust it at scale. If you didn't set this up,
   show the annotation queue and describe the loop in two sentences.
6. **Live mini-run (1 min, ~60-90s wall time)**:
   ```bash
   python -m evals.run_experiment --examples inv-pay-small,inv-over-po,inv-fraud --no-judges --prefix live-demo
   ```
   Open the link it prints and watch the rows fill in. Three examples, three different ledger
   outcomes, all checked in code.
7. **Production loop (1 min, UI)**: tracing project → **Evaluators** (online LLM-as-judge on
   a sample of live runs, e.g. the groundedness prompt) → **Automations** rule (low score or
   thumbs-down → annotation queue) → reviewer clicks **Add to dataset**. *"Production failures
   become test cases. The golden set grows from real traffic."* Mention **Engine** (Plus /
   Enterprise): clusters failures into issues, proposes a fix PR and an online evaluator;
   Engine v2 adds red teaming and validates fixes against the eval set before deploy.
8. **CI (30 s)**: `pytest` (29 offline tests, ~10s, scripted models prove the guarantees) and
   `evals/test_live.py` (`@pytest.mark.langsmith`: the four guarantees with real models,
   logged as a LangSmith test suite). `python -m evals.simulate` if asked about multi-turn:
   a simulated vendor tries, over four turns, to get bank details changed.

### F. Why LangChain (4 min): tie each point to something they just saw
1. **Open and model-agnostic.** Every model is a `provider:model` string; `--main-model
   anthropic:claude-sonnet-4-6` re-runs the same dataset on another vendor. The fallback
   model is one middleware line.
2. **Middleware is production control without forking the agent loop.** Identity, PII,
   audit, limits, fallback, approvals compose, and they're unit-testable (29 tests, 10s).
3. **Deep Agents is a proven harness, and it's files.** AGENTS.md, skills, permissions,
   specialists, memory. The sales team owns the playbooks; engineering owns the wiring.
4. **The LangGraph runtime is durability.** Checkpoints, interrupts that wait, time travel,
   streaming; the same graph runs in Studio and in production.
5. **LangSmith is the improvement loop, and it works with any framework.** Traces → dataset
   → experiments → calibrated judges → online evals → annotation → Engine. *"Without it the
   agent looked fine. With it I found N issues in an afternoon and can prove each fix."*
   (Fill in N from Wednesday's baseline.)

### G. Close (2 min): what I'd do with a real customer next week
1. Trace their existing agent in LangSmith on day 1 (any framework).
2. Build a 30-50 example golden set from real traces through an annotation queue; label 20
   for judge calibration.
3. Baseline experiment: code checks + calibrated judges. Fix the top 3 issues with middleware,
   tool design and specialists; prove it in the compare view.
4. CI gate on the smoke split, online evals on 10% of traffic, automation to the queue.
5. Deploy on LangSmith Deployment with the interrupt API wired to their approval UI.

---

## 2. The LangSmith features, one by one (how to demo each)

### 2.1 Evals
- **In code** (`evals/`): `aevaluate(target, data, evaluators, summary_evaluators, num_repetitions,
  max_concurrency, metadata)`. The target is async because the MCP tools are; it auto-approves
  pauses the way a reviewer would and records which actions paused.
- **What to say**: evals are software; they have bugs too (the round-2 story of concurrent runs
  sharing one DB is why `isolated_ledger` is a `ContextVar` and why the mailbox is reset per
  example).
- **Show**: the evaluator table in `evals/evaluators.py` header; one `SKIP` (not applicable
  never counts as a pass).

### 2.2 Datasets & Experiments
- **Dataset**: `python -m evals.dataset` creates/updates examples in place by stable id, so
  experiments stay attached. Splits `smoke`/`full`. Metadata `category`, `key`.
- **Experiments**: `--prefix`, `--reps`, `--variant`, `--main-model`. Metadata chips on the
  experiment (variant, models, git sha) make the compare view self-explanatory.
- **UI**: Datasets & Experiments → dataset → Experiments tab → select 2 → **Compare**; toggle
  "show only regressions"; click a cell → trace. Charts tab for scores over time.
- **Also**: examples can be added from a trace ("Add to dataset") and, since September, whole
  threads from an annotation queue as multi-turn examples.

### 2.3 LLM-as-judge
- **Offline, in code**: `openevals.create_llm_as_judge` with `CORRECTNESS_PROMPT` and a custom
  groundedness prompt; `create_trajectory_llm_as_judge` for paths. Judge model ≠ agent model
  (`JUDGE_MODEL`) to avoid self-preference.
- **In the UI**: dataset → Evaluators → + Evaluator → LLM-as-a-judge; prompt variables like
  `{{inputs.question}}`, `{{outputs.answer}}`, `{{reference_outputs.answer}}`; run it on an
  existing experiment without re-running the agent.
- **Calibration**: Align Evaluator (annotation queue labels → alignment score). Say the two
  rules: judges see what the agent saw; judges are checked against humans before you trust them.
- **Online**: the same judge on live traces, sampled, with a spend cap.

### 2.4 LangSmith Studio
- `./start.sh` → Studio at `smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`, graph
  `sales_assistant`. Set **context** `{"rep_id": 3}`.
- What to show: the graph with middleware nodes; the **interrupt panel** (approve / edit /
  reject, and `pay_invoice` only offers approve/reject, by config); **threads**; **time travel**
  (fork from a checkpoint, edit, re-run); the link from a Studio run to its LangSmith trace.
- The async graph factory (`make_graph`) is why the mail tools appear without a restart if
  you start the mail server late; Studio re-loads the graph per run until discovery succeeds.

### 2.5 Other features: what to add, and what to skip

| Feature | Verdict | Why / how |
|---|---|---|
| **Tracing + Trajectory view** | **Add (must)** | Everything else is built on it; 1 minute, opens §E. |
| **Annotation queues + Align Evaluator** | **Add (must)** | Answers "how do you trust the judge?", the question you'll get. 15 min setup. |
| **Online evaluators + Automations → dataset** | **Add** | Closes the loop from production to the golden set. UI only, 2 min in the demo. |
| **Compare view with repetitions** | **Add** | Shows variance; the no-skills A/B is the most convincing 60 seconds you have. |
| **Studio time travel + edit decision** | **Add if time** | Cheap, memorable, shows the checkpoint model. |
| **Playground** | Optional | Iterate the ap-auditor prompt or a judge prompt against a saved trace. Nice if a question comes up. |
| **Prompt Hub / prompt versioning** | Mention | Say why your prompts live in files (skills, AGENTS.md) and how a customer without git discipline would use the Hub. |
| **Monitoring dashboards + alerts** | Mention (1 slide/screen) | Cost, latency, tokens, feedback over time; alert on error rate. Business audiences like this screen. |
| **Engine / Insights** | Mention; show if your plan has it | Clusters failures, root causes, fix PRs, red teaming (v2). Don't build the demo on it. |
| **pytest integration** (`test_live.py`) | Show 30 s | "CI gate" is a phrase enterprise buyers understand. |
| **Multi-turn simulation** (`simulate.py`) | Have ready | Run it if asked about conversations or social engineering. |
| **Deployment** | One sentence | Kevin's original brief said not to show deployments; say the same `langgraph.json` deploys and move on. |
| **Fleet / Managed Deep Agents / Custom Apps / Fine-tuning** | Vocabulary only | Shows you follow the roadmap; not demo material. |

---

## 3. What changed since the Chinook Concierge (if Kevin has seen round 2)
- New domain: internal sales assistant; actions with real consequences (payments, refunds, mail).
- **MCP**: the mailbox is an MCP server; tools discovered at startup; privilege split by name.
- **Four specialists** including one whose only job is to read untrusted input.
- **Three approval gates**: always-on (refund), conditional (payment, `when`), and an MCP tool
  (send_email) with reviewer edits.
- **Code behind every gate** (`validate_payment`, invoice ownership/amount checks) and an
  **audit trail** middleware.
- **The repo as the filesystem** with permission rules; AGENTS.md as reviewable memory.
- **Evals that check state, not just text**: `ledger_state`, `deliverable`, `no_secret_leak`,
  `action_safety`; an A/B variant switch (`--variant no-skills`); a fraud simulation.

## 4. If something breaks
- **Mail server down**: the agent starts without mail tools and says so; `python mcp/mail_server.py`
  in another tab, next run picks the tools up. That's a feature; say so.
- **Studio misbehaves**: `python scripts/chat.py` shows the same interrupts in the terminal;
  `python -m evals.target "Pay the CloudStack invoice CS-77213 for $349 against PO-1051"` prints a
  full run as JSON. Then show the pre-run traces.
- **Slow model / 429**: "this is exactly why there's a fallback model and call limits"; switch to
  pre-run traces and the compare view.
- **Second run of a payment says "already paid"**: by design (duplicate check). `./start.sh --reset`.
- **The quote shortfall (15 Bossa Nova tracks)**: if the agent doesn't mention it, that's your live
  example of a skill fix: add a line to `rfq-quote/SKILL.md` and re-run.

## 5. Vocabulary: use the current names
LangSmith Deployment (was LangGraph Platform) · LangSmith Studio (was LangGraph Studio) · Agent
Server (was LangGraph Server) · LangSmith Fleet (was Agent Builder) · Trajectory view /
Trajectories · Engine, Engine v2 · Managed Deep Agents · Align Evaluator · Insights.

## 6. Ten questions you'll get (30-second answers, then point at code)
1. **Why an async graph factory?** MCP tools are discovered over the network before the graph
   exists; `langgraph dev` awaits `make_graph`. The graph is cached once discovery succeeds.
2. **Why not give the inbox-clerk `send_email`?** Least privilege: the agent that reads untrusted
   content must not be the one that can act on it. Prompt injection in an email lands in a
   context window that can only read.
3. **How does the `when` predicate know the invoice is valid?** It runs the same `validate_payment`
   the tool runs. Invalid → no pause, tool refuses. Valid and large → pause. Valid and small → pay.
4. **What if the reviewer approves something wrong?** Code still validates: PO match, balance,
   duplicates, refund ≤ invoice total. Approval is necessary, not sufficient.
5. **Where does the agent's memory live and who can change it?** `/AGENTS.md` in the repo,
   written only for standing instructions, reviewed with `git diff`, reset with `git checkout`.
6. **How do you keep the judge honest?** Judge model ≠ agent model; judge sees the app context;
   Align Evaluator against ~20 human labels; re-check when the prompt changes.
7. **Why sequential evals?** The mailbox and `output/` are shared state. The target resets the
   mailbox per example; the ledger is per-run via a `ContextVar`. Parallelize by giving each
   worker its own mail server port if you need speed.
8. **What does middleware buy me over a custom graph?** Cross-cutting control on the standard
   loop without forking it; composable, testable, visible as nodes in Studio. Custom graphs are
   for bespoke control flow; they compose with agents as nodes.
9. **Cost and latency?** Specialists on the cheap model, main agent on the strong one; prompt
   caching on the stable prefix; call limits bound the worst case. Read the numbers off the
   experiment metadata.
10. **What would you change for production?** Real mail MCP server with auth, LangSmith
    Deployment (persistence, interrupt API), an approval UI in Slack or the CRM, online evals on
    10% of traffic, the golden set fed from the annotation queue.
