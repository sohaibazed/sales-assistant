from __future__ import annotations

import re

from langchain.agents.middleware import PIIMatch

_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _luhn(digits: str) -> bool:
    total = 0
    for i, digit in enumerate(reversed(digits)):
        value = int(digit) * (2 if i % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def detect_credit_cards(text: str) -> list[PIIMatch]:
    return [
        {
            "type": "credit_card",
            "value": match.group(),
            "start": match.start(),
            "end": match.end(),
        }
        for match in _CARD.finditer(text)
        if 13 <= len(re.sub(r"\D", "", match.group())) <= 19
        and _luhn(re.sub(r"\D", "", match.group()))
    ]


def _card_numbers(text: str) -> list[str]:
    return [re.sub(r"\D", "", match["value"]) for match in detect_credit_cards(text)]
