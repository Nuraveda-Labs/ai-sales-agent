"""One-shot North York cannabis-retailer discovery.

Runs four text-search variants against Places API (New), dedups on
`place.id`, maps to `LeadCreate`, and upserts into `sales_agent.leads`.
Idempotent — re-running picks up new shops without duplicating existing
ones (LeadRepo.upsert is COALESCE-protected).

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.discovery.run_north_york
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sales_agent.db import LeadRepo, pool
from sales_agent.db.models import LeadCreate
from sales_agent.discovery.google_places import default_client

logger = logging.getLogger(__name__)

# Text search beats nearby search for retail discovery — the geographic
# intent is in the query and Places (New) ranks by relevance to the text.
QUERIES: tuple[str, ...] = (
    "cannabis store North York Toronto",
    "cannabis store York Toronto",
    "dispensary North York Toronto",
    "weed store North York Toronto",
)


def _component(place: dict[str, Any], *types: str) -> str | None:
    """Pull a single value out of `place.addressComponents` by type."""
    for c in place.get("addressComponents", []) or []:
        type_set = set(c.get("types", []))
        if type_set & set(types):
            return c.get("longText") or c.get("shortText")
    return None


def place_to_lead(place: dict[str, Any]) -> LeadCreate:
    """Map a Places-API-(New) place dict to a LeadCreate payload.

    Skips fields the API didn't return rather than emitting empty strings —
    the upsert is COALESCE-protected and downstream enrichment fills in
    what discovery couldn't.
    """
    name = (place.get("displayName") or {}).get("text") or "Unknown"
    location = place.get("location") or {}

    return LeadCreate(
        source="google_places",
        source_id=place["id"],
        business_name=name,
        address=place.get("formattedAddress"),
        city=_component(place, "locality", "sublocality") or None,
        province=_component(place, "administrative_area_level_1") or "ON",
        postal_code=_component(place, "postal_code"),
        lat=location.get("latitude"),
        lng=location.get("longitude"),
        phone=place.get("nationalPhoneNumber"),
        website_url=place.get("websiteUri"),
    )


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
        for query in QUERIES:
            places = await client.search_text_all(query)
            for p in places:
                seen.setdefault(p["id"], p)

        logger.info("discovery: %d unique places across %d queries", len(seen), len(QUERIES))

        new_count = 0
        with_email_unknown = 0  # Places never returns email; enrichment fills it
        with_website = 0
        with_phone = 0

        for place in seen.values():
            payload = place_to_lead(place)
            lead = await repo.upsert(payload)
            new_count += 1
            if payload.website_url:
                with_website += 1
            if payload.phone:
                with_phone += 1
            with_email_unknown += 1

            logger.info(
                "  → %-40s | %s | site=%s phone=%s",
                lead.business_name[:40],
                lead.city or "?",
                "Y" if payload.website_url else "·",
                "Y" if payload.phone else "·",
            )

        logger.info(
            "discovery done: written=%d websites=%d phones=%d emails=0 (next: enrichment)",
            new_count, with_website, with_phone,
        )
    finally:
        await client.aclose()
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
