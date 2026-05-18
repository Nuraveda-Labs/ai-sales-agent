"""Re-scan every lead to populate `pos_platform`.

Different from `run_enrichment` — that runs once on `status='new'` and
transitions to `enriched`. This is an idempotent rescan that updates
`pos_platform` in place regardless of status, without disturbing the
funnel state. Re-runs are safe.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.enrichment.run_pos_rescan
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter

import httpx

from sales_agent.db import LeadRepo, pool
from sales_agent.db.models import Lead, LeadEnrichment
from sales_agent.enrichment.site_detector import detect_pos_platform

logger = logging.getLogger(__name__)

CONCURRENCY = 12
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}


async def _all_leads(p, *, only_unclassified: bool = True) -> list[Lead]:
    """By default, scan only leads that don't yet have a pos_platform set
    AND aren't paused (chain filter pauses anything we wouldn't pitch
    anyway, no point re-fetching their sites). Pass only_unclassified=False
    to force a full re-scan of every lead in the DB."""
    where = "WHERE 1=1"
    if only_unclassified:
        where += " AND pos_platform IS NULL AND status != 'paused'"
    sql = f"""
    SELECT id, created_at, updated_at, source, source_id, agco_license,
           business_name, address, city, province, postal_code, lat, lng,
           phone, website_url, instagram_handle, contact_email,
           contact_email_source, contact_email_verified,
           current_site_status, pos_platform,
           score, status, paused_at, paused_reason, notes,
           hubspot_contact_id, hubspot_company_id, hubspot_deal_id, hubspot_synced_at
    FROM sales_agent.leads
    {where}
    ORDER BY business_name
    """
    async with p.acquire() as conn:
        rows = await conn.fetch(sql)
    return [Lead.model_validate(dict(r)) for r in rows]


async def rescan_one(
    lead: Lead, repo: LeadRepo, client: httpx.AsyncClient, sem: asyncio.Semaphore,
) -> str:
    async with sem:
        platform = await detect_pos_platform(lead.website_url, client)
    await repo.update_enrichment(lead.id, LeadEnrichment(pos_platform=platform))
    logger.info("  %-45s | %s", lead.business_name[:45], platform)
    return platform


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    await pool.connect(min_size=1, max_size=4)
    repo = LeadRepo(pool.pool())
    sem = asyncio.Semaphore(CONCURRENCY)

    try:
        leads = await _all_leads(pool.pool())
        logger.info("rescanning %d leads for pos_platform", len(leads))

        async with httpx.AsyncClient(headers=HTTP_HEADERS) as client:
            results = await asyncio.gather(
                *(rescan_one(l, repo, client, sem) for l in leads),
                return_exceptions=True,
            )

        dist: Counter[str] = Counter()
        for r in results:
            if isinstance(r, BaseException):
                dist["__error__"] += 1
                continue
            dist[r] += 1
        logger.info("rescan done. distribution: %s", dict(dist))
    finally:
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
