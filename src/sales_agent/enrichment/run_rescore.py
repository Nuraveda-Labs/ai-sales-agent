"""Re-score every lead in-place (no status transitions).

Use this after a recipe / pos_platform / scoring-heuristic change so the
existing cohort gets the new priority order without losing funnel state.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.enrichment.run_rescore
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter

from sales_agent.db import LeadRepo, pool
from sales_agent.db.models import Lead, LeadEnrichment
from sales_agent.enrichment.score import _domain_of, domain_counts, score_lead

logger = logging.getLogger(__name__)


async def _all_leads(p) -> list[Lead]:
    sql = """
    SELECT id, created_at, updated_at, source, source_id, agco_license,
           business_name, address, city, province, postal_code, lat, lng,
           phone, website_url, instagram_handle, contact_email,
           contact_email_source, contact_email_verified,
           current_site_status, pos_platform,
           score, status, paused_at, paused_reason, notes,
           hubspot_contact_id, hubspot_company_id, hubspot_deal_id, hubspot_synced_at
    FROM sales_agent.leads
    ORDER BY business_name
    """
    async with p.acquire() as conn:
        rows = await conn.fetch(sql)
    return [Lead.model_validate(dict(r)) for r in rows]


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    await pool.connect(min_size=1, max_size=2)
    repo = LeadRepo(pool.pool())

    try:
        leads = await _all_leads(pool.pool())
        logger.info("rescoring %d leads", len(leads))

        counts = domain_counts(leads)
        bucket: Counter[str] = Counter()
        scored: list[tuple[int, str]] = []

        for lead in leads:
            d = _domain_of(lead.website_url) or ""
            count = counts.get(d, 1)
            new_score, reasons = score_lead(lead, domain_count=count)
            await repo.update_enrichment(
                lead.id, LeadEnrichment(score=new_score),
            )
            scored.append((new_score, lead.business_name))

            if new_score >= 80:
                bucket["A_high"] += 1
            elif new_score >= 60:
                bucket["B_mid"] += 1
            elif new_score >= 40:
                bucket["C_low"] += 1
            else:
                bucket["D_skip"] += 1

        scored.sort(key=lambda t: -t[0])
        logger.info("--- top 15 ---")
        for s, n in scored[:15]:
            logger.info("  %3d  %s", s, n[:55])
        logger.info("--- bottom 10 ---")
        for s, n in scored[-10:]:
            logger.info("  %3d  %s", s, n[:55])
        logger.info("rescore done. distribution: %s", dict(bucket))
    finally:
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
