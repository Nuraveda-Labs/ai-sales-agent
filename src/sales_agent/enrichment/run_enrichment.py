"""Enrich every `status='new'` lead.

For each lead with a website_url, run the site classifier + contact-email
finder concurrently across the cohort (semaphore-bounded). Update the row
via `LeadRepo.update_enrichment` and transition to `status='enriched'`.

Idempotent — re-running picks up only leads still in `new`. Leads with no
website are marked site_status=`none` and skipped on the email side.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.enrichment.run_enrichment
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter

import httpx

from sales_agent.db import LeadRepo, pool
from sales_agent.db.models import Lead, LeadEnrichment
from sales_agent.enrichment.contact_finder import find_contact_email
from sales_agent.enrichment.site_detector import detect as detect_site

logger = logging.getLogger(__name__)

CONCURRENCY = 10
HTTP_HEADERS = {
    # <industry>-shop sites often Cloudflare-block on missing UA. Use a
    # plausible browser UA so we don't get false `none` classifications.
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}


async def enrich_one(
    lead: Lead, repo: LeadRepo, client: httpx.AsyncClient, sem: asyncio.Semaphore,
) -> dict[str, object]:
    async with sem:
        site_status = await detect_site(lead.website_url, client)
        email, email_src = await find_contact_email(lead.website_url, site_status, client)

    patch = LeadEnrichment(
        contact_email=email,
        contact_email_source=email_src,
        contact_email_verified=False,
        current_site_status=site_status,
    )
    await repo.update_enrichment(lead.id, patch)
    await repo.transition(
        lead.id,
        "enriched",
        event_type="enriched",
        metadata={
            "site_status": site_status,
            "email_source": email_src or "none",
        },
    )

    logger.info(
        "  %-40s | %-10s | %s",
        lead.business_name[:40], site_status, email or "—",
    )
    return {"site_status": site_status, "email_source": email_src}


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    await pool.connect(min_size=1, max_size=4)
    repo = LeadRepo(pool.pool())
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(headers=HTTP_HEADERS) as client:
        leads = await repo.by_status("new", limit=500)
        logger.info("enrichment: %d leads to process", len(leads))

        results = await asyncio.gather(
            *(enrich_one(lead, repo, client, sem) for lead in leads),
            return_exceptions=True,
        )

    site_dist: Counter[str] = Counter()
    email_dist: Counter[str] = Counter()
    failures = 0
    for r in results:
        if isinstance(r, BaseException):
            failures += 1
            continue
        site_dist[str(r["site_status"])] += 1
        email_dist[str(r["email_source"] or "none")] += 1

    logger.info("enrichment done.")
    logger.info("  site_status: %s", dict(site_dist))
    logger.info("  email_source: %s", dict(email_dist))
    logger.info("  failures: %d", failures)

    await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
