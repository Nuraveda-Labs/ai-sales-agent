"""Brand fact sheet resolution — private playbook with public stub fallback.

Same import-fallback pattern as `recipes.py`. The drafter pastes the
returned string into Claude's system context as immutable brand facts.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_STUB_FACT_SHEET = (
    "# Brand fact sheet (placeholder)\n\n"
    "Install the `ai_marketing_stack-sales-playbook` private package to load the\n"
    "calibrated brand fact sheet. Drafts produced against this stub will\n"
    "compile but will not contain real product details.\n"
)


def get_brand_fact_sheet() -> str:
    try:
        from ai_marketing_stack_sales_playbook.brand import BRAND_FACT_SHEET  # type: ignore[import-not-found]

        return BRAND_FACT_SHEET
    except ImportError:
        logger.warning("brand: private playbook not installed — using stub fact sheet")
        return _STUB_FACT_SHEET
