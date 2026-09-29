"""Create or update the golden dataset in LangSmith.

    python -m evals.dataset            # create the dataset, or add/update examples in place

Examples have stable ids (uuid5 of their key), so re-running updates them in place and every
existing experiment stays attached to the same examples.
"""

from __future__ import annotations

from dotenv import load_dotenv
from langsmith import Client

from .examples import DATASET_NAME, build_examples


def sync_dataset(client: Client | None = None) -> str:
    load_dotenv()
    client = client or Client()
    examples = build_examples()
    if client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
    else:
        dataset = client.create_dataset(
            DATASET_NAME,
            description="Golden set for the Chinook sales assistant: analytics, inbox, payments, refunds, workflows, security.",
        )
    existing = {str(e.id) for e in client.list_examples(dataset_id=dataset.id)}
    new = [e for e in examples if e["id"] not in existing]
    old = [e for e in examples if e["id"] in existing]
    if new:
        client.create_examples(dataset_id=dataset.id, examples=new)
    for e in old:
        client.update_example(e["id"], inputs=e["inputs"], outputs=e["outputs"], metadata=e["metadata"], split=e["split"])
    print(f"{DATASET_NAME}: {len(new)} created, {len(old)} updated ({len(examples)} total)")
    return DATASET_NAME


if __name__ == "__main__":
    sync_dataset()
