"""A terminal chat with the assistant, including the human-approval prompts.

    python scripts/chat.py                 # rep 3 (Jane)
    python scripts/chat.py --rep 4         # Margaret

Use it as a fallback if Studio misbehaves in the demo, or to show the interrupt/resume
protocol programmatically: the same `Command(resume={"decisions": [...]})` that Studio and
the Agent Server API send.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from agent import build_agent  # noqa: E402
from config import Context  # noqa: E402
from tools.mail import discover_mail_tools  # noqa: E402


def decide(action: dict, allowed: list[str]) -> dict:
    print(f"\n⏸  {action['name']} wants to run with:\n{json.dumps(action['args'], indent=2)}")
    choice = ""
    while choice not in allowed:
        choice = input(f"   [{'/'.join(allowed)}] > ").strip().lower()
    if choice == "approve":
        return {"type": "approve"}
    if choice == "reject":
        return {"type": "reject", "message": input("   reason > ").strip() or "Rejected by reviewer"}
    edited = json.loads(input("   new args (JSON) > ") or "{}") or action["args"]
    return {"type": "edit", "edited_action": {"name": action["name"], "args": edited}}


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rep", type=int, default=3)
    args = p.parse_args()

    tools = await discover_mail_tools()
    print(f"mail tools: {[t.name for t in tools] or 'NONE (start python mcp/mail_server.py)'}")
    agent = build_agent(mail_tools=tools, checkpointer=InMemorySaver())
    context = Context(rep_id=args.rep)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 150}
    print("Chinook Sales Assistant. Ctrl-D to quit.\n")

    while True:
        try:
            text = input("you > ").strip()
        except EOFError:
            break
        if not text:
            continue
        payload = {"messages": [HumanMessage(text)]}
        while True:
            async for namespace, update in agent.astream(payload, config, context=context, stream_mode="updates", subgraphs=True):
                for value in (update or {}).values():
                    if not isinstance(value, dict):
                        continue
                    for msg in value.get("messages") or []:
                        prefix = "   ↳ " if namespace else "   "
                        if isinstance(msg, AIMessage) and msg.tool_calls:
                            for c in msg.tool_calls:
                                print(f"{prefix}{c['name']}({json.dumps(c['args'], default=str)[:120]})")
                        elif isinstance(msg, ToolMessage):
                            print(f"{prefix}→ {msg.text[:160].replace(chr(10), ' ')}")
            state = await agent.aget_state(config)
            if not state.interrupts:
                break
            decisions = []
            for intr in state.interrupts:
                configs = {c["action_name"]: c["allowed_decisions"] for c in intr.value.get("review_configs", [])}
                for action in intr.value["action_requests"]:
                    decisions.append(decide(action, configs.get(action["name"], ["approve", "reject"])))
            payload = Command(resume={"decisions": decisions})
        final = next((m for m in reversed(state.values["messages"]) if isinstance(m, AIMessage) and m.text.strip()), None)
        print(f"\nassistant > {final.text if final else '(no answer)'}\n")


if __name__ == "__main__":
    asyncio.run(main())
