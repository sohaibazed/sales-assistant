from langchain.agents.middleware import PIIMiddleware
from langchain_core.messages import HumanMessage

from pii import detect_credit_cards


def test_credit_card_middleware_masks_luhn_valid_card_lengths():
    middleware = PIIMiddleware(
        "credit_card",
        strategy="mask",
        detector=detect_credit_cards,
        apply_to_input=True,
    )
    amex = "3782 822463 10005"
    visa = "4111 1111 1111 1111"
    state = {"messages": [HumanMessage(f"Amex {amex}; Visa {visa}")]}

    result = middleware.before_model(state, None)

    masked = result["messages"][0].text
    assert amex not in masked
    assert visa not in masked
    assert "0005" in masked
    assert "1111" in masked


def test_credit_card_middleware_ignores_non_luhn_numbers():
    middleware = PIIMiddleware(
        "credit_card",
        strategy="mask",
        detector=detect_credit_cards,
        apply_to_input=True,
    )
    order_id = "3782 822463 10006"
    state = {"messages": [HumanMessage(f"Order {order_id}")]}

    assert middleware.before_model(state, None) is None
