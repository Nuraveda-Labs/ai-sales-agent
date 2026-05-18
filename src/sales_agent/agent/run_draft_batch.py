"""Draft cold emails for the top-N scored leads.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.agent.run_draft_batch --limit 5
    PYTHONPATH=src python3 -m sales_agent.agent.run_draft_batch --limit 33   # all A-tier

Drafts are written to `sales_agent.email_drafts` with `approval_state='pending'`
and the lead transitions `scored → drafted`. Nothing is sent — the Discord
HITL surface is the next sprint. Inspect drafts via:

    psql "$POSTGRES_RW_URL" -c \\
      "SELECT subject, body FROM sales_agent.email_drafts ORDER BY created_at DESC LIMIT 5"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import textwrap

from sales_agent.agent.drafter import Drafter
from sales_agent.db import DraftRepo, LeadRepo, pool
from sales_agent.db.models import EmailDraftCreate, Lead

logger = logging.getLogger(__name__)


async def _top_scored_with_email(repo_pool, limit: int) -> list[Lead]:
    sql = """
    SELECT
        id, created_at, updated_at,
        source, source_id, agco_license,
        business_name, address, city, province, postal_code, lat, lng,
        phone, website_url, instagram_handle, contact_email,
        contact_email_source, contact_email_verified,
        current_site_status, pos_platform,
        score, status, paused_at, paused_reason, notes,
        hubspot_contact_id, hubspot_company_id, hubspot_deal_id, hubspot_synced_at
    FROM sales_agent.leads
    WHERE status = 'scored'
      AND contact_email IS NOT NULL
    ORDER BY score DESC, created_at ASC
    LIMIT $1
    """
    async with repo_pool.acquire() as conn:
        rows = await conn.fetch(sql, limit)
    return [Lead.model_validate(dict(r)) for r in rows]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print drafts to stdout in addition to writing them to the DB",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    await pool.connect(min_size=1, max_size=2)
    p = pool.pool()
    lead_repo = LeadRepo(p)
    draft_repo = DraftRepo(p)
    drafter = Drafter()

    try:
        leads = await _top_scored_with_email(p, args.limit)
        if not leads:
            logger.info("drafter: no scored leads with email — nothing to do")
            return

        logger.info(
            "drafter: drafting %d leads (model=%s, top score=%d)",
            len(leads), drafter.model, leads[0].score,
        )

        total_in = 0
        total_out = 0
        ok_count = 0
        fail_count = 0
        for lead in leads:
            try:
                result = await drafter.draft(lead)
            except Exception as e:
                logger.error("drafter: failed for %s: %s", lead.business_name, e)
                fail_count += 1
                continue

            recipe_key = result.recipe_key or (lead.pos_platform or lead.current_site_status or "custom")
            draft = await draft_repo.insert(EmailDraftCreate(
                lead_id=lead.id,
                recipe_key=recipe_key,
                subject_variant=result.subject_variant,
                subject=result.subject,
                body=result.body,
                model=result.model,
                model_input_tokens=result.input_tokens,
                model_output_tokens=result.output_tokens,
                prior_context_ids=[],
            ))
            await lead_repo.transition(
                lead.id, "drafted",
                event_type="drafted",
                metadata={
                    "draft_id": str(draft.id),
                    "recipe_key": recipe_key,
                    "subject_variant": result.subject_variant,
                },
            )
            total_in += result.input_tokens
            total_out += result.output_tokens
            ok_count += 1

            logger.info(
                "  ✓ %3d  %-40s | %s",
                lead.score, lead.business_name[:40], result.subject,
            )

            if args.preview:
                indent = "      "
                logger.info("%sto: %s", indent, lead.contact_email)
                logger.info("%ssubject: %s", indent, result.subject)
                wrapped = textwrap.indent(result.body, indent)
                logger.info("%sbody:\n%s", indent, wrapped)
                logger.info("%s---", indent)

        logger.info(
            "drafter done: ok=%d failed=%d tokens in=%d out=%d",
            ok_count, fail_count, total_in, total_out,
        )
    finally:
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
