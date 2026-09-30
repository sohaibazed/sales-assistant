"""Create one assistant per sales rep on the running Agent Server (langgraph dev or LangSmith
Deployment). An assistant is a configured instance of a graph: same code, different default
context. That is how a UI that has no "context" field (Agent Chat, Slack, a CRM widget) signs
a rep in: it talks to the rep's assistant, and the run context carries their rep_id.

    ./start.sh                              # in one terminal
    python scripts/create_assistants.py     # prints the assistant ids to paste into Agent Chat

Re-running updates the assistants in place (stable ids derived from the rep id).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph_sdk import get_sync_client  # noqa: E402

from tools.sql import query  # noqa: E402

GRAPH_ID = "sales_assistant"
_NS = uuid.UUID("2f1c3b3a-8e4d-4a7f-9c6e-5d1b0a9e7c21")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:2024", help="Agent Server URL (langgraph dev default)")
    args = p.parse_args()
    client = get_sync_client(url=args.url)

    reps = query("SELECT EmployeeId, FirstName, LastName FROM Employee WHERE Title = 'Sales Support Agent' ORDER BY EmployeeId")
    for rep in reps:
        name = f"Sales assistant for {rep['FirstName']} {rep['LastName']}"
        assistant = client.assistants.create(
            graph_id=GRAPH_ID,
            assistant_id=str(uuid.uuid5(_NS, str(rep["EmployeeId"]))),
            name=name,
            context={"rep_id": rep["EmployeeId"]},
            metadata={"rep_id": rep["EmployeeId"]},
            if_exists="do_nothing",
        )
        # if_exists="do_nothing" keeps an existing assistant; make sure its context is current.
        client.assistants.update(assistant["assistant_id"], graph_id=GRAPH_ID, name=name, context={"rep_id": rep["EmployeeId"]})
        print(f"{assistant['assistant_id']}  {name}  context={{'rep_id': {rep['EmployeeId']}}}")
    print("\nAgent Chat: Deployment URL = the server URL above; Assistant / Graph ID = one of the ids above.")


if __name__ == "__main__":
    main()
