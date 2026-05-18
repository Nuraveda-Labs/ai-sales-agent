"""One-shot pipeline + custom-property bootstrap.

Run once after rotating the PAT and writing it to .env:

    python -m sales_agent.hubspot.bootstrap_pipeline

Idempotent — safe to re-run after schema changes in `stages.py`. New
stages get added; existing stages are left alone (you'd hand-fix any
drift in the HubSpot UI rather than letting this script clobber them).
"""

from __future__ import annotations

import asyncio
import logging

from sales_agent.config import settings
from sales_agent.hubspot import client, pipelines

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    if not settings.hubspot_pat:
        raise SystemExit("HUBSPOT_PAT not set in .env")

    logger.info("bootstrap: ensuring custom properties …")
    await pipelines.ensure_custom_properties()

    logger.info("bootstrap: ensuring pipeline %r …", settings.hubspot_pipeline_name)
    pipeline_id = await pipelines.ensure_pipeline()

    logger.info("bootstrap: done. pipeline_id=%s", pipeline_id)
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
