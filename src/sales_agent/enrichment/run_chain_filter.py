"""Pre-filter chain-location leads before enrichment.

Cannabis retail in Ontario has a long tail of multi-location chains
(Tokyo Smoke, Spiritleaf, Canna Cabana, Fire & Flower, One Plant,
Sessions, Hunny Pot, FIKA, etc.). At Discovery scale (655+ leads
across the GTA), pulling all their storefronts means doubling the
enrichment cost on shops the drafter scoring already benches out of
the queue (-30 chain keyword + -30 multi-location domain → score < 40).

This pre-filter pauses chain leads BEFORE we hit their websites with
the site detector + contact_finder. It saves ~30 minutes of API calls
+ scrapes per discovery batch and keeps the operator's HubSpot
pipeline view focused on real prospects.

Two detection methods:
1. **Keyword match** — `business_name` contains a known chain
   identifier (single source of truth: `score.CHAIN_KEYWORDS`).
2. **Multi-location domain** — same `website_url` host appears 3+
   times across `status='new'` leads. Catches chains we haven't
   added to the keyword list yet.

Pauses with `paused_reason='chain_location'`. Idempotent: re-running
won't re-pause already-paused rows because the SQL filter is
`WHERE status='new'`.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.enrichment.run_chain_filter
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter

from sales_agent.db import LeadRepo, pool
from sales_agent.db.models import Lead
from sales_agent.enrichment.score import CHAIN_KEYWORDS, _domain_of, _matches_chain

logger = logging.getLogger(__name__)

# Domain appearing N+ times across the cohort triggers chain auto-detect.
DOMAIN_CHAIN_THRESHOLD = 3


async def _new_leads(p) -> list[Lead]:
    sql = """
    SELECT id, created_at, updated_at, source, source_id, agco_license,
           business_name, address, city, province, postal_code, lat, lng,
           phone, website_url, instagram_handle, contact_email,
           contact_email_source, contact_email_verified,
           current_site_status, pos_platform,
           score, status, paused_at, paused_reason, notes,
           hubspot_contact_id, hubspot_company_id, hubspot_deal_id, hubspot_synced_at
    FROM sales_agent.leads
    WHERE status = 'new'
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
        leads = await _new_leads(pool.pool())
        logger.info("chain filter: scanning %d status='new' leads", len(leads))

        # Pass 1: count domain occurrences across the cohort.
        domain_counts: Counter[str] = Counter()
        for lead in leads:
            d = _domain_of(lead.website_url)
            if d:
                domain_counts[d] += 1

        chain_domains = {
            d for d, n in domain_counts.items() if n >= DOMAIN_CHAIN_THRESHOLD
        }
        logger.info(
            "  → %d distinct chain-domains (≥%d locations)",
            len(chain_domains), DOMAIN_CHAIN_THRESHOLD,
        )
        if chain_domains:
            for d in sorted(chain_domains, key=lambda d: -domain_counts[d])[:10]:
                logger.info("    %-40s %d locations", d, domain_counts[d])

        # Pass 2: pause anything matching a keyword OR a chain domain.
        kept = 0
        paused_by_keyword = 0
        paused_by_domain = 0

        for lead in leads:
            kw_match = _matches_chain(lead.business_name)
            dom = _domain_of(lead.website_url)
            dom_match = dom in chain_domains if dom else False

            if kw_match:
                await repo.pause(lead.id, reason="chain_location:keyword", actor="chain_filter")
                paused_by_keyword += 1
            elif dom_match:
                await repo.pause(
                    lead.id,
                    reason=f"chain_location:domain={dom}({domain_counts[dom]})",
                    actor="chain_filter",
                )
                paused_by_domain += 1
            else:
                kept += 1

        logger.info(
            "chain filter done: paused=%d (kw=%d, domain=%d) kept=%d",
            paused_by_keyword + paused_by_domain,
            paused_by_keyword, paused_by_domain, kept,
        )
        logger.info("known-chain keyword set: %d entries", len(CHAIN_KEYWORDS))
    finally:
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
