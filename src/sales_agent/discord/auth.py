"""Admin gate for Discord interactions.

Only Discord user IDs in `DISCORD_ADMIN_USER_IDS` can approve / reject / edit
drafts. Reactions from non-admins are ignored silently — we don't react back
("permission denied") because cluttering the channel for non-admin pokes is
worse than letting them no-op.
"""

from __future__ import annotations

from sales_agent.config import settings


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_user_id_list


def actor(user_id: int) -> str:
    """Format a Discord user id for the email_drafts.approved_by_text column."""
    return f"discord:{user_id}"
