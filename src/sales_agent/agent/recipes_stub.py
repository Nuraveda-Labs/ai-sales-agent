"""Placeholder recipes — public, deliberately generic.

Real Glitch Budz copy lives in the private `ai_marketing_stack_sales_playbook`
package and overrides this stub at import time (see `sales_agent.agent.recipes`).

Data model (v3):
    Recipe   keyed on `pos_platform` enum
       └─ hooks: tuple[Hook, ...]  — multiple angles per platform
                                     for A/B variety; drafter picks one
                                     deterministically per lead via hash
            └─ Hook
                  name      — short identifier for analytics ("chains_have",
                              "chatgpt_test", "time_budget", "ai_shift")
                  subjects  — subject-line variants for this hook
                  opener    — first sentence (or "" to omit)
                  body      — value-prop prose; URL block + signature
                              get appended by the render layer per format
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Hook:
    """One framing angle for cold email 1.

    Each Hook is fully self-contained — different subject, opener, and body.
    The recipe library lists multiple Hooks per platform so a 30-lead batch
    gets natural variety without manual rotation.
    """

    name: str
    subjects: tuple[str, ...]
    opener: str
    body: str


@dataclass(frozen=True)
class Recipe:
    """Per-platform recipe: a set of Hooks the drafter rotates between."""

    key: str
    hooks: tuple[Hook, ...]


_PLACEHOLDER = Hook(
    name="placeholder",
    subjects=("(placeholder subject)",),
    opener="(placeholder opener)",
    body="(placeholder body — install ai_marketing_stack_sales_playbook for real copy)",
)


# Stub: one placeholder hook per platform. Override in playbook.
RECIPES: dict[str, Recipe] = {
    key: Recipe(key=key, hooks=(_PLACEHOLDER,))
    for key in ("none", "brochure", "dutchie", "blaze", "tendypos", "shopify", "custom")
}
