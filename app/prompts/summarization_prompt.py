PROMPT_VERSION = "v1.0.0"

SUMMARIZATION_PROMPT_TEMPLATE = """Summarize the following list of qualified \
leads into a short, scannable briefing for a sales rep (SDR), in French. \
Group by priority (P0 first). One line per lead: name, training, priority, \
and the single most important thing to know before calling.

Leads:
{leads_block}
"""


def build_summarization_prompt(leads_block: str) -> str:
    return SUMMARIZATION_PROMPT_TEMPLATE.format(leads_block=leads_block)
