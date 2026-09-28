PROMPT_VERSION = "v1.0.0"

QUALIFICATION_PROMPT_TEMPLATE = """Analyse the following prospect message and \
return ONLY a JSON object with this exact shape:

{{
  "intent": "information_request" | "ready_to_pay" | "objection" | "complaint" | "other",
  "urgency": "low" | "medium" | "high",
  "summary": "one sentence summary in French",
  "suggested_next_action": "one short sentence in French"
}}

Prospect message:
\"\"\"{raw_message}\"\"\"

Training requested: {training}
"""


def build_qualification_prompt(raw_message: str, training: str) -> str:
    return QUALIFICATION_PROMPT_TEMPLATE.format(raw_message=raw_message, training=training)
