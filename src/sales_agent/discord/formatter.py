"""Format a draft + lead into a Discord embed.

The embed is the primary operator surface — what they see in #sales-agent
when a fresh draft lands. Layout choices:

- **Title** = subject line (most-scanned element).
- **Description** = body, fenced as a quote block so newlines render and
  the bold markdown survives.
- **Fields** = quick-glance metadata: score, site_status, recipe, to:.
- **Footer** = draft id + reaction key. The id is the operator's only way
  to find the row in psql if they need to inspect deeper.
- **Color** changes per state so a scrolled-back queue is readable:
  pending=blue, approved=green, rejected=red, edited=amber.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

from sales_agent.db.models import EmailDraft, Lead

# Discord embed description hard cap is 4096; leave headroom for formatting.
_BODY_BUDGET = 3800


_STATE_COLOR = {
    "pending":    0x3498DB,  # blue
    "approved":   0x2ECC71,  # green
    "rejected":   0xE74C3C,  # red
    "edited":     0xF1C40F,  # amber
    "superseded": 0x95A5A6,  # gray
}


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def draft_embed(
    draft: EmailDraft,
    lead: Lead,
    *,
    state_override: str | None = None,
) -> "discord.Embed":
    import discord

    state = state_override or draft.approval_state
    color = _STATE_COLOR.get(state, 0x3498DB)

    body = _truncate(draft.body, _BODY_BUDGET)
    description = f"```\n{body}\n```"

    embed = discord.Embed(
        title=_truncate(draft.subject, 256),
        description=description,
        color=color,
        timestamp=datetime.utcnow(),
    )
    embed.set_author(name=lead.business_name)
    embed.add_field(name="To",      value=lead.contact_email or "(unknown)", inline=False)
    embed.add_field(name="Score",   value=str(lead.score),                    inline=True)
    embed.add_field(name="Site",    value=lead.current_site_status or "?",    inline=True)
    embed.add_field(name="Recipe",  value=draft.recipe_key,                   inline=True)
    embed.add_field(name="Subject variant", value=f"`{draft.subject_variant}`", inline=False)

    state_line = f"State: **{state}**"
    if draft.approved_by_text:
        state_line += f" by {draft.approved_by_text}"
    embed.add_field(name="​", value=state_line, inline=False)

    embed.set_footer(text=f"draft {draft.id} · ✅ send · ❌ kill · 🖊️ edit")
    return embed
