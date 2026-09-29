#!/usr/bin/env bash
# Start the mail MCP server, then `langgraph dev` (LangSmith Studio). Ctrl-C stops both.
#
#   ./start.sh            # normal start
#   ./start.sh --reset    # also wipe demo state: ledger (payments/refunds/audit) and Studio threads
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "--reset" ]]; then
  rm -f data/ledger.sqlite
  rm -rf .langgraph_api
  git checkout -- AGENTS.md 2>/dev/null || true   # forget anything the agent learned during rehearsal
  echo "Reset: ledger, Studio threads and AGENTS.md."
fi

if [[ ! -f .env ]]; then
  echo "No .env found. Copy .env.example to .env and add your keys." >&2
  exit 1
fi

python mcp/mail_server.py &
MAIL_PID=$!
trap 'kill $MAIL_PID 2>/dev/null || true' EXIT

# Wait until the mail server answers, so the agent discovers its tools on the first run.
for _ in $(seq 1 30); do
  if curl -s -o /dev/null "http://127.0.0.1:${MAIL_MCP_PORT:-8765}/mcp"; then break; fi
  sleep 0.2
done

exec langgraph dev "$@"
