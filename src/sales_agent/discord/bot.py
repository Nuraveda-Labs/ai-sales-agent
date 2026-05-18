"""Discord bot — long-lived gateway connection, reaction-driven HITL.

Workflow:
    1. Drafter (separate process / cron) writes new pending drafts to DB.
    2. This bot's poll loop scans every POLL_INTERVAL_S seconds for drafts
       with approval_state='pending' AND discord_message_id IS NULL,
       posts an embed to the configured approval channel for each, and
       writes the resulting (channel_id, message_id) back so the row is
       linked to its embed.
    3. Operator reacts on the embed:
         ✅  → mark_approved (sender will pick it up next sprint)
         ❌  → mark_rejected (lead stays drafted; can be redrafted later)
         🖊️  → mark_edit_requested (operator follows up in-thread)
       The bot edits the embed in-place to reflect the new state +
       approver, so a scrolled-back queue stays readable.

Run with:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.discord.bot

Required .env:
    DISCORD_BOT_TOKEN              # from Discord Developer Portal → Bot tab
    DISCORD_GUILD_ID               # right-click your server → "Copy Server ID"
    DISCORD_APPROVAL_CHANNEL_ID    # right-click the channel → "Copy Channel ID"
    DISCORD_ADMIN_USER_IDS         # comma-separated; right-click your user → "Copy User ID"

Bot needs the `Send Messages`, `Embed Links`, `Add Reactions`, `Read Message
History` permissions on the approval channel. Privileged Gateway Intents
(message content, presence) are NOT needed.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from sales_agent.config import settings
from sales_agent.db import DraftRepo, LeadRepo, pool
from sales_agent.discord.auth import actor, is_admin
from sales_agent.discord.formatter import draft_embed

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 30
REACTION_APPROVE = "✅"
REACTION_REJECT = "❌"
REACTION_EDIT = "🖊️"
RECOGNISED_REACTIONS = (REACTION_APPROVE, REACTION_REJECT, REACTION_EDIT)


async def _build_client():
    """Construct the discord.Client lazily so the import doesn't run at module load."""
    import discord

    intents = discord.Intents.default()
    # We don't need message_content (privileged); reactions are in default intents.

    client = discord.Client(intents=intents)

    # Cached repos + state. Initialized in setup().
    state: dict[str, object] = {
        "pool": None,
        "lead_repo": None,
        "draft_repo": None,
        "channel": None,
        "poll_task": None,
    }

    @client.event
    async def on_ready() -> None:
        logger.info("discord: connected as %s (id=%s)", client.user, client.user.id if client.user else "?")
        await pool.connect(min_size=1, max_size=4)
        state["pool"] = pool.pool()
        state["lead_repo"] = LeadRepo(state["pool"])
        state["draft_repo"] = DraftRepo(state["pool"])

        if not settings.discord_approval_channel_id:
            logger.error("discord: DISCORD_APPROVAL_CHANNEL_ID not set; bot will idle")
            return
        chan = client.get_channel(int(settings.discord_approval_channel_id))
        if chan is None:
            try:
                chan = await client.fetch_channel(int(settings.discord_approval_channel_id))
            except discord.NotFound:
                logger.error("discord: approval channel not found / bot not in server")
                return
        state["channel"] = chan
        logger.info("discord: approval channel = #%s", getattr(chan, "name", chan.id))

        # Kick the polling loop.
        if state["poll_task"] is None or state["poll_task"].done():  # type: ignore[union-attr]
            state["poll_task"] = asyncio.create_task(_poll_loop(client, state))

    @client.event
    async def on_raw_reaction_add(payload: "discord.RawReactionActionEvent") -> None:
        # Ignore the bot's own bootstrap reactions.
        if client.user and payload.user_id == client.user.id:
            return
        if int(settings.discord_approval_channel_id or 0) and payload.channel_id != int(
            settings.discord_approval_channel_id
        ):
            return

        emoji = str(payload.emoji)
        if emoji not in RECOGNISED_REACTIONS:
            return
        if not is_admin(payload.user_id):
            logger.info("discord: ignored reaction from non-admin %s", payload.user_id)
            return

        draft_repo = state["draft_repo"]
        lead_repo = state["lead_repo"]
        if draft_repo is None or lead_repo is None:
            return

        draft = await draft_repo.by_discord_message(payload.message_id)  # type: ignore[union-attr]
        if draft is None:
            return
        if draft.approval_state != "pending":
            return  # already resolved by an earlier reaction

        approver = actor(payload.user_id)
        new_state: str
        if emoji == REACTION_APPROVE:
            await draft_repo.mark_approved(draft.id, approver=approver)  # type: ignore[union-attr]
            new_state = "approved"
        elif emoji == REACTION_REJECT:
            await draft_repo.mark_rejected(draft.id, approver=approver)  # type: ignore[union-attr]
            new_state = "rejected"
        else:  # REACTION_EDIT
            await draft_repo.mark_edit_requested(  # type: ignore[union-attr]
                draft.id, approver=approver,
                edit_request="(operator requested edit; reply to the embed to specify)",
            )
            new_state = "edited"

        # Re-fetch + edit the embed in place.
        fresh_draft = await draft_repo.get(draft.id)  # type: ignore[union-attr]
        lead = await lead_repo.get(draft.lead_id)  # type: ignore[union-attr]
        if fresh_draft and lead:
            try:
                msg = await state["channel"].fetch_message(payload.message_id)  # type: ignore[union-attr]
                await msg.edit(embed=draft_embed(fresh_draft, lead))
            except Exception:
                logger.exception("discord: failed to edit embed after reaction")

        logger.info("discord: draft %s → %s by %s", draft.id, new_state, approver)

    return client


async def _poll_loop(client, state: dict) -> None:
    """Poll the DB every POLL_INTERVAL_S seconds for unposted pending drafts."""
    import discord

    while not client.is_closed():
        try:
            await _post_pending(state)
        except Exception:
            logger.exception("discord: poll iteration failed")
        await asyncio.sleep(POLL_INTERVAL_S)


async def _post_pending(state: dict) -> None:
    draft_repo: DraftRepo = state["draft_repo"]  # type: ignore[assignment]
    lead_repo: LeadRepo = state["lead_repo"]  # type: ignore[assignment]
    channel = state["channel"]
    if channel is None:
        return

    pending = await draft_repo.pending(limit=50)
    fresh = [d for d in pending if d.discord_message_id is None]
    if not fresh:
        return

    logger.info("discord: posting %d new drafts", len(fresh))
    for draft in fresh:
        lead = await lead_repo.get(draft.lead_id)
        if lead is None:
            continue
        embed = draft_embed(draft, lead)
        try:
            msg = await channel.send(embed=embed)
            for emoji in RECOGNISED_REACTIONS:
                await msg.add_reaction(emoji)
            await draft_repo.attach_discord(
                draft.id, channel_id=msg.channel.id, message_id=msg.id,
            )
        except Exception:
            logger.exception("discord: failed to post draft %s", draft.id)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not settings.discord_bot_token:
        sys.exit("DISCORD_BOT_TOKEN not set in .env")
    if not settings.discord_approval_channel_id:
        sys.exit("DISCORD_APPROVAL_CHANNEL_ID not set in .env")
    if not settings.admin_user_id_list:
        sys.exit("DISCORD_ADMIN_USER_IDS empty — refusing to start (anyone could approve sends)")

    client = await _build_client()
    try:
        await client.start(settings.discord_bot_token)
    finally:
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
