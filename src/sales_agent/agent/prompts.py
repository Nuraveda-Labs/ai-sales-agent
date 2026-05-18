"""System-prompt resolution — tries the private playbook, falls back to stub.

The private playbook's prompt encodes brand voice rules, content
constraints, and hard limits (word cap, no invented prices, no AGCO
"certified" claims). Public stub is generic.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_STUB_SYSTEM = (
    "You are an outbound-sales drafter. Write a concise, direct cold email "
    "based on the recipe and lead facts provided. Output JSON: "
    '{"subject_variant": "...", "subject": "...", "body": "..."}.'
)


def get_system_prompt() -> str:
    try:
        from ai_marketing_stack_sales_playbook.prompts.system import SYSTEM  # type: ignore[import-not-found]

        return SYSTEM
    except ImportError:
        logger.warning("prompts: private playbook not installed — using stub system prompt")
        return _STUB_SYSTEM
