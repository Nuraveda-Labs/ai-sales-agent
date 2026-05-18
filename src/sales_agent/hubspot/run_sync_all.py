"""One-shot: sync every enriched lead into HubSpot.

Pumps all `status='enriched'` (and beyond) leads into HubSpot Contacts,
Companies, and Deals via the sync layer. Idempotent — re-running picks
up only leads whose `hubspot_synced_at` is older than their `updated_at`,
so a refresh cycle after a re-enrichment is cheap.

For v0 we sync everything that has a non-NULL HubSpot stage map
(`leads.status` ∈ {enriched, scored, drafted, sent, opened, replied,
booked, dead} — i.e., not `new` and not `paused`). Concurrency is
bounded so we never approach the HubSpot 100-req/10s standard-tier
ceiling.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.hubspot.run_sync_all
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter

from sales_agent.config import settings
from sales_agent.db import LeadRepo, SendRepo, pool
from sales_agent.db.models import Lead
from sales_agent.hubspot import client, sync

logger = logging.getLogger(__name__)

CONCURRENCY = 5  # 5 × ~6 calls/lead ≈ 30 calls/sec headroom under 100/10s
SYNCABLE_STATUSES = (
    "enriched", "scored", "drafted", "sent", "opened", "replied",
    "booked", "dead",
)


async def _sync_one(
    lead: Lead, lead_repo: LeadRepo, sem: asyncio.Semaphore,
) -> tuple[str, bool]:
    async with sem:
        updated = await sync.sync_lead(lead_repo, lead)
    ok = bool(updated.hubspot_company_id or updated.hubspot_deal_id or updated.hubspot_contact_id)
    return lead.business_name, ok


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not settings.hubspot_sync_enabled:
        raise SystemExit("HUBSPOT_SYNC_ENABLED is false in .env — refusing to run")
    if not settings.hubspot_pat:
        raise SystemExit("HUBSPOT_PAT not set in .env")

    await pool.connect(min_size=1, max_size=4)
    lead_repo = LeadRepo(pool.pool())
    _ = SendRepo(pool.pool())  # unused here, but warms import

    try:
        leads: list[Lead] = []
        for status in SYNCABLE_STATUSES:
            leads.extend(await lead_repo.by_status(status, limit=10_000))  # type: ignore[arg-type]

        logger.info("hubspot.sync: %d leads to sync", len(leads))

        sem = asyncio.Semaphore(CONCURRENCY)
        results = await asyncio.gather(
            *(_sync_one(l, lead_repo, sem) for l in leads),
            return_exceptions=True,
        )

        outcomes: Counter[str] = Counter()
        for r in results:
            if isinstance(r, BaseException):
                outcomes["exception"] += 1
                continue
            _, ok = r
            outcomes["synced" if ok else "skipped"] += 1

        logger.info("hubspot.sync done: %s", dict(outcomes))

        # Final tally from the DB itself — don't trust the in-flight counters.
        async with pool.pool().acquire() as conn:
            tally = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE hubspot_contact_id IS NOT NULL) AS with_contact,
                    COUNT(*) FILTER (WHERE hubspot_company_id IS NOT NULL) AS with_company,
                    COUNT(*) FILTER (WHERE hubspot_deal_id    IS NOT NULL) AS with_deal,
                    COUNT(*) AS total
                FROM sales_agent.leads
            """)
        logger.info(
            "DB tally: contacts=%d companies=%d deals=%d / %d leads",
            tally["with_contact"], tally["with_company"],
            tally["with_deal"], tally["total"],
        )
    finally:
        await client.aclose()
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
