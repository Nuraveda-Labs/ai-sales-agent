"""Score every enriched lead, transition to `status='scored'`.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.enrichment.run_scoring
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter

from sales_agent.db import LeadRepo, pool
from sales_agent.db.models import LeadEnrichment
from sales_agent.enrichment.score import _domain_of, domain_counts, score_lead

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    await pool.connect(min_size=1, max_size=2)
    repo = LeadRepo(pool.pool())

    try:
        leads = await repo.by_status("enriched", limit=10_000)
        logger.info("scoring: %d leads", len(leads))

        counts = domain_counts(leads)
        bucket: Counter[str] = Counter()

        # Sort the print-out by score desc so the operator can eyeball
        # whether the heuristic ordered things correctly.
        scored: list[tuple[int, str, list[str]]] = []
        for lead in leads:
            d = _domain_of(lead.website_url) or ""
            count = counts.get(d, 1)

            score, reasons = score_lead(lead, domain_count=count)
            scored.append((score, lead.business_name, reasons))

            await repo.update_enrichment(
                lead.id, LeadEnrichment(score=score),
            )
            await repo.transition(
                lead.id, "scored", event_type="scored",
                metadata={"score": score, "reasons": reasons},
            )

            if score >= 80:
                bucket["A_high"] += 1
            elif score >= 60:
                bucket["B_mid"] += 1
            elif score >= 40:
                bucket["C_low"] += 1
            else:
                bucket["D_skip"] += 1

        scored.sort(key=lambda t: -t[0])
        logger.info("--- top 20 by score ---")
        for score, name, _reasons in scored[:20]:
            logger.info("  %3d  %s", score, name[:60])
        logger.info("--- bottom 10 by score ---")
        for score, name, _reasons in scored[-10:]:
            logger.info("  %3d  %s", score, name[:60])

        logger.info("scoring done. distribution: %s", dict(bucket))
    finally:
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
