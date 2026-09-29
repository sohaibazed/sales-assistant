"""Run an experiment against the golden dataset and log it to LangSmith.

    python -m evals.run_experiment                          # full agent, all examples
    python -m evals.run_experiment --variant no-skills      # A/B: the same agent without playbooks
    python -m evals.run_experiment --split smoke --no-judges  # fast, code checks only (CI)
    python -m evals.run_experiment --examples inv-pay-small,inv-fraud,ref-defective --prefix live-demo
    python -m evals.run_experiment --main-model anthropic:claude-sonnet-4-6   # vendor swap, same dataset

Compare experiments in LangSmith: Datasets & Experiments -> sales-assistant-golden -> select
two experiments -> Compare. The mail server must be running (python mcp/mail_server.py).
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess

from dotenv import load_dotenv
from langsmith import Client, aevaluate

from .dataset import sync_dataset
from .evaluators import CODE_EVALUATORS, LLM_EVALUATORS, action_safety
from .target import assistant_target


async def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--variant", choices=["full", "no-skills"], default="full")
    p.add_argument("--main-model")
    p.add_argument("--subagent-model")
    p.add_argument("--split", choices=["smoke", "full", "all"], default="all")
    p.add_argument("--no-judges", action="store_true", help="code evaluators only (fast, free)")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--concurrency", type=int, default=1, help="the mailbox is shared state; keep 1 unless --examples avoids it")
    p.add_argument("--prefix")
    p.add_argument("--examples", help="comma-separated example keys to run (default: all in the split)")
    args = p.parse_args()

    client = Client()
    dataset = sync_dataset(client)
    data = list(client.list_examples(dataset_name=dataset, splits=None if args.split == "all" else [args.split]))
    if args.examples:
        keys = set(args.examples.split(","))
        data = [e for e in data if e.metadata.get("key") in keys]

    from config import MAIN_MODEL, SUBAGENT_MODEL

    target = assistant_target(main_model=args.main_model, subagent_model=args.subagent_model, use_skills=args.variant == "full")
    sha = subprocess.run(["git", "describe", "--always", "--dirty"], capture_output=True, text=True).stdout.strip()
    metadata = {
        "variant": args.variant,
        "main_model": args.main_model or MAIN_MODEL,
        "subagent_model": args.subagent_model or SUBAGENT_MODEL,
        "split": args.split,
        "git_sha": sha,
    }
    await aevaluate(
        target,
        data=data,
        evaluators=CODE_EVALUATORS + ([] if args.no_judges else LLM_EVALUATORS),
        summary_evaluators=[action_safety],
        experiment_prefix=args.prefix or args.variant,
        metadata=metadata,
        num_repetitions=args.reps,
        max_concurrency=args.concurrency,
        client=client,
    )


if __name__ == "__main__":
    asyncio.run(main())
