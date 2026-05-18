"""One-shot: replay every historical email_send as a HubSpot engagement.

Used after a HubSpot account swap (or any time email_sends rows have a
NULL hubspot_engagement_id). Pulls every send that's missing an
engagement id, builds a HubSpot Email engagement payload from the
stored snapshot (subject + body + sent_at + from/to), POSTs it, and
links it to the lead's deal + contact via associations.

Idempotent: rows that already have hubspot_engagement_id set are
skipped, so re-runs don't duplicate.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.hubspot.run_replay_engagements
"""

from __future__ import annotations

import asyncio
import logging

from sales_agent.config import settings
from sales_agent.db import LeadRepo, SendRepo, pool
from sales_agent.db.models import EmailSend, Lead
from sales_agent.hubspot import client as hub_client
from sales_agent.hubspot import sync as hub_sync

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not settings.hubspot_sync_enabled or not settings.hubspot_pat:
        raise SystemExit("HubSpot sync disabled or PAT missing")

    await pool.connect(min_size=1, max_size=2)
    p = pool.pool()
    lead_repo = LeadRepo(p)
    send_repo = SendRepo(p)

    try:
        async with p.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id, created_at, lead_id, draft_id,
                    gmail_message_id, gmail_thread_id,
                    from_email, to_email, subject, body,
                    tracking_pixel_id, sent_at,
                    opened_first_at, opened_count,
                    replied_at, reply_thread_count,
                    bounced, unsubscribed, follow_up_seq
                FROM sales_agent.email_sends
                WHERE hubspot_engagement_id IS NULL
                ORDER BY sent_at
                """
            )

        logger.info("replay: %d sends missing engagement_id", len(rows))
        ok = 0
        fail = 0
        skip_no_deal = 0

        for r in rows:
            send = EmailSend.model_validate(dict(r))
            lead = await lead_repo.get(send.lead_id)
            if lead is None or lead.hubspot_deal_id is None:
                logger.warning(
                    "skip send=%s lead=%s — no hubspot_deal_id (lead missing or not synced)",
                    send.id, send.lead_id,
                )
                skip_no_deal += 1
                continue

            try:
                await hub_sync.sync_send(send_repo, lead, send)
                ok += 1
                logger.info(
                    "✓ %-40s  resend_id=%s",
                    lead.business_name[:40], send.gmail_message_id,
                )
            except Exception:
                logger.exception("✗ replay failed for send=%s", send.id)
                fail += 1

        logger.info(
            "replay done. ok=%d fail=%d skip_no_deal=%d",
            ok, fail, skip_no_deal,
        )
    finally:
        await hub_client.aclose()
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
