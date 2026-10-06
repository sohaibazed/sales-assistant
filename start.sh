#!/usr/bin/env bash
# Start the mail MCP server, the data specialist (data_agent/, its own venv and Agent Server),
# the newsletter writer (newsletter_agent/, its own Agent Server on this venv),
# then `langgraph dev` (LangSmith Studio) for the main agent. Ctrl-C stops all four.
#
#   ./start.sh            # normal start
#   ./start.sh --reset    # also wipe demo state: ledger (payments/refunds/audit) and Studio threads
set -euo pipefail
cd "$(dirname "$0")"

DATA_AGENT_PORT="${DATA_AGENT_PORT:-2025}"
NEWSLETTER_AGENT_PORT="${NEWSLETTER_AGENT_PORT:-2026}"

if [[ "${1:-}" == "--reset" ]]; then
  rm -f data/ledger.sqlite
  rm -rf .langgraph_api data_agent/.langgraph_api newsletter_agent/.langgraph_api
  git checkout -- AGENTS.md 2>/dev/null || true   # forget anything the agent learned during rehearsal
  echo "Reset: ledger, Studio threads and AGENTS.md."
  shift   # don't forward --reset to `langgraph dev`
fi

if [[ ! -f .env ]]; then
  echo "No .env found. Copy .env.example to .env and add your keys." >&2
  exit 1
fi

if [[ ! -x data_agent/.venv/bin/langgraph ]]; then
  echo "Data specialist not installed. Run: cd data_agent && python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

python mcp/mail_server.py &
MAIL_PID=$!

# The specialist reads the same .env as the main agent (one place for keys, no copy inside
# data_agent/). Loaded in a subshell so nothing leaks into this script's environment.
(
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  cd data_agent
  exec .venv/bin/langgraph dev --port "${DATA_AGENT_PORT}" --no-browser
) > data_agent/server.log 2>&1 &
DATA_PID=$!

# The newsletter writer imports this project's tools, so it runs on this venv; its
# langgraph.json loads ../.env.
(
  cd newsletter_agent
  exec langgraph dev --port "${NEWSLETTER_AGENT_PORT}" --no-browser
) > newsletter_agent/server.log 2>&1 &
NEWSLETTER_PID=$!

trap 'kill "$MAIL_PID" "$DATA_PID" "$NEWSLETTER_PID" 2>/dev/null || true' EXIT

# The main agent wires in the specialist only when DATA_AGENT_URL is set (see config.py).
export DATA_AGENT_URL="${DATA_AGENT_URL:-http://127.0.0.1:${DATA_AGENT_PORT}}"
export NEWSLETTER_AGENT_URL="${NEWSLETTER_AGENT_URL:-http://127.0.0.1:${NEWSLETTER_AGENT_PORT}}"

# Wait until the mail server answers, so the agent discovers its tools on the first run.
for _ in $(seq 1 30); do
  if curl -s -o /dev/null "http://127.0.0.1:${MAIL_MCP_PORT:-8765}/mcp"; then break; fi
  sleep 0.2
done

# Wait for the specialist too (it is only called on delegation, but fail loudly if it didn't start).
for _ in $(seq 1 150); do
  if curl -sf -o /dev/null "http://127.0.0.1:${DATA_AGENT_PORT}/ok"; then break; fi
  sleep 0.2
done
if ! curl -sf -o /dev/null "http://127.0.0.1:${DATA_AGENT_PORT}/ok"; then
  echo "Data specialist did not start; see data_agent/server.log. Continuing without it." >&2
  unset DATA_AGENT_URL
fi

for _ in $(seq 1 150); do
  if curl -sf -o /dev/null "http://127.0.0.1:${NEWSLETTER_AGENT_PORT}/ok"; then break; fi
  sleep 0.2
done
if ! curl -sf -o /dev/null "http://127.0.0.1:${NEWSLETTER_AGENT_PORT}/ok"; then
  echo "Newsletter writer did not start; see newsletter_agent/server.log. The main agent will write newsletters itself." >&2
  unset NEWSLETTER_AGENT_URL
fi

exec langgraph dev "$@"
