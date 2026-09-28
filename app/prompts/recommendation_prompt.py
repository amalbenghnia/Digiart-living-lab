PROMPT_VERSION = "v1.0.0"

RECOMMENDATION_PROMPT_TEMPLATE = """Given this lead's current state, suggest \
the single next action for the sales rep, in French, in one short sentence. \
Do not suggest a discount or a price change — that decision is never made \
by you.

Lead status: {status}
Priority: {priority}
Days since last contact: {days_since_contact}
Payment status: {payment_status}
"""


def build_recommendation_prompt(
    status: str, priority: str, days_since_contact: int, payment_status: str
) -> str:
    return RECOMMENDATION_PROMPT_TEMPLATE.format(
        status=status, priority=priority,
        days_since_contact=days_since_contact, payment_status=payment_status,
    )
