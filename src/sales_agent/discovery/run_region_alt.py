"""<industry> retailer discovery — Downtown <region>.

Targets the high-density downtown corridors directly with neighbourhood-
specific queries instead of relying on Google's fuzzy geographic
matching on broader "<region>" terms (which is what fed Old <region>
leads into the <region> / GTA passes incidentally).

Coverage:
- Generic downtown ("downtown <region>")
- Major corridors with the highest <industry>-retail density:
  Yonge Street, Queen Street West / Queen West, Kensington Market,
  Liberty Village, King Street West / King West, The Annex,
  Dundas West, Roncesvalles, Leslieville, The Beach, Distillery
- Two query templates per corridor (<industry> / business)

Dedup is automatic via LeadRepo.upsert (source, source_id) — anything
the GTA pass already pulled stays untouched, only new ones land.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.discovery.run_region_alt
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any

from sales_agent.db import LeadRepo, pool
from sales_agent.discovery.google_places import default_client
from sales_agent.discovery.run_region import place_to_lead

logger = logging.getLogger(__name__)


# Each entry is the location-bias term that goes into the query string.
CORRIDORS = (
    "downtown <region>",
    "Yonge Street <region>",
    "Queen Street West <region>",
    "Kensington Market <region>",
    "Liberty Village <region>",
    "King Street West <region>",
    "The Annex <region>",
    "Dundas West <region>",
    "Roncesvalles <region>",
    "Leslieville <region>",
    "The Beaches <region>",
    "Distillery District <region>",
)

QUERY_TEMPLATES = (
    "<industry> store {area}",
    "business {area}",
)


def queries() -> list[str]:
    return [t.format(area=a) for a in CORRIDORS for t in QUERY_TEMPLATES]


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    await pool.connect(min_size=1, max_size=2)
    repo = LeadRepo(pool.pool())
    client = default_client()

    seen: dict[str, dict[str, Any]] = {}
    try:
        qs = queries()
        for q in qs:
            places = await client.search_text_all(q)
            for p in places:
                seen.setdefault(p["id"], p)

        logger.info(
            "discovery: %d unique places across %d queries",
            len(seen), len(qs),
        )

        async with pool.pool().acquire() as conn:
            rows = await conn.fetch(
                "SELECT source_id FROM sales_agent.leads "
                "WHERE source = 'google_places' AND source_id = ANY($1::text[])",
                list(seen.keys()),
            )
        existing_ids = {r["source_id"] for r in rows}
        new_ids = set(seen.keys()) - existing_ids
        logger.info("  → %d already in DB, %d new", len(existing_ids), len(new_ids))

        with_website = 0
        per_city: Counter[str] = Counter()

        for place in seen.values():
            payload = place_to_lead(place)
            await repo.upsert(payload)
            if payload.website_url:
                with_website += 1
            per_city[payload.city or "?"] += 1

        logger.info(
            "discovery done: total=%d new=%d websites=%d",
            len(seen), len(new_ids), with_website,
        )
        logger.info("--- by city ---")
        for city, n in per_city.most_common():
            logger.info("  %-20s %d", city, n)
    finally:
        await client.aclose()
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
