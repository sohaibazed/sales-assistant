"""Tool code. Each tool is given to the one agent that needs it (see agent.py / subagents.py):

    sql.py     -> chinook-analyst subagent   (read-only SQL over the sales database)
    search.py  -> genre-researcher subagent  (web search, with an offline fallback)
    ledger.py  -> ap-auditor subagent (lookups) and the main agent (pay_invoice, issue_refund: gated)
    html.py    -> main agent                 (builds HTML deliverables under output/)
    chart.py   -> main agent                 (renders charts for the territory report)
    mail.py    -> discovers the mail MCP server's tools at startup (read tools -> inbox-clerk,
                  send_email -> main agent, gated)
"""
