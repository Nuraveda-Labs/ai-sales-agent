"""<industry> retailer discovery — Greater <region> Area expansion.

Same architecture as run_north_york: Google Places (New) text search,
dedup on place_id, idempotent upsert into sales_agent.leads. Skips any
shop we already have via LeadRepo.upsert's COALESCE on (source, source_id).

Coverage:
- The 7 surrounding GTA cities (Mississauga, Brampton, Vaughan, Markham,
  Richmond Hill, Oakville, Burlington)
- Deeper sweeps of the <region> boroughs we have only thin coverage on
  from the <region> pass (Etobicoke, Scarborough, East York)

Two query templates per city ("<industry> store" + "dispensary") gives
the widest catch with reasonable API cost — the dedup absorbs overlaps.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.discovery.run_gta
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any

from sales_agent.db import LeadRepo, pool
from sales_agent.db.models import LeadCreate
from sales_agent.discovery.google_places import default_client
from sales_agent.discovery.run_north_york import place_to_lead

logger = logging.getLogger(__name__)


CITIES = (
    # Major GTA suburbs
    "Mississauga",
    "Brampton",
    "Vaughan",
    "Markham",
    "Richmond Hill",
    "Oakville",
    "Burlington",
    # <region> boroughs we under-covered in the <region> pass
    "Etobicoke",
    "Scarborough",
    "East York",
)

QUERY_TEMPLATES = (
    "<industry> store {city} Ontario",
    "dispensary {city} Ontario",
)


def queries() -> list[str]:
    return [t.format(city=c) for c in CITIES for t in QUERY_TEMPLATES]


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
        for q in queries():
            places = await client.search_text_all(q)
            for p in places:
                seen.setdefault(p["id"], p)

        logger.info(
            "discovery: %d unique places across %d queries (%d cities × %d templates)",
            len(seen), len(CITIES) * len(QUERY_TEMPLATES), len(CITIES), len(QUERY_TEMPLATES),
        )

        # How many of these are already in the DB? Check before upsert.
        existing_ids = set()
        async with pool.pool().acquire() as conn:
            rows = await conn.fetch(
                "SELECT source_id FROM sales_agent.leads "
                "WHERE source = 'google_places' AND source_id = ANY($1::text[])",
                list(seen.keys()),
            )
            existing_ids = {r["source_id"] for r in rows}

        new_ids = set(seen.keys()) - existing_ids
        logger.info(
            "  → %d already in DB, %d new",
            len(existing_ids), len(new_ids),
        )

        # Upsert all (idempotent — existing rows refresh fields without
        # losing enrichment columns thanks to LeadRepo.upsert COALESCE).
        with_website = 0
        with_phone = 0
        per_city: Counter[str] = Counter()

        for place in seen.values():
            payload = place_to_lead(place)
            await repo.upsert(payload)
            if payload.website_url:
                with_website += 1
            if payload.phone:
                with_phone += 1
            per_city[payload.city or "?"] += 1

        logger.info(
            "discovery done: total=%d new=%d websites=%d phones=%d",
            len(seen), len(new_ids), with_website, with_phone,
        )
        logger.info("--- by city (top 15) ---")
        for city, n in per_city.most_common(15):
            logger.info("  %-20s %d", city, n)
    finally:
        await client.aclose()
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
