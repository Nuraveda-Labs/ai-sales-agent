"""Send every `approval_state='approved'` draft that hasn't been sent yet.

Pre-flight checks before each send:
- Daily cap not exceeded (settings.outreach_daily_cap, default 5; ramps
  over warm-up).
- Recipient not in sales_agent.unsubscribes.
- Recipient has a contact_email (sanity).

Per send:
1. send_plain via Resend
2. INSERT INTO sales_agent.email_sends with the resend message id
3. transition lead → status='sent', event_type='sent'
4. fire HubSpot sync_send to log the engagement on the deal timeline

Idempotency: the Resend `Idempotency-Key` is set to `draft:<draft_id>`,
so re-running this script after a partial failure won't double-send.
The DB-side INSERT into email_sends has a unique constraint on
gmail_message_id (== resend message id) — if a row already exists for
this resend id, the second INSERT fails fast with a clear error.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent
    source .venv/bin/activate
    PYTHONPATH=src python3 -m sales_agent.mail.run_send_approved [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sales_agent.config import settings
from sales_agent.db import DraftRepo, LeadRepo, SendRepo, UnsubRepo, pool
from sales_agent.db.models import EmailDraft, EmailSendCreate, Lead
from sales_agent.hubspot import client as hub_client
from sales_agent.hubspot import sync as hub_sync
from sales_agent.mail import gmail_sender, resend_sender

logger = logging.getLogger(__name__)


async def _approved_drafts(p, limit: int) -> list[tuple[EmailDraft, Lead]]:
    """Pull up to N approved drafts that have NOT been sent yet, joined to lead."""
    sql = """
    SELECT d.id AS draft_id, d.created_at, d.lead_id, d.recipe_key,
           d.subject_variant, d.subject, d.body, d.model,
           d.model_input_tokens, d.model_output_tokens, d.model_cost_usd,
           d.prior_context_ids, d.approval_state, d.approved_by_text,
           d.approved_at, d.edit_request,
           d.discord_message_id, d.discord_channel_id,
           l.id AS lead_id_full, l.created_at AS lead_created, l.updated_at,
           l.source, l.source_id, l.agco_license,
           l.business_name, l.address, l.city, l.province, l.postal_code,
           l.lat, l.lng,
           l.phone, l.website_url, l.instagram_handle, l.contact_email,
           l.contact_email_source, l.contact_email_verified,
           l.current_site_status, l.pos_platform,
           l.score, l.status, l.paused_at, l.paused_reason, l.notes,
           l.hubspot_contact_id, l.hubspot_company_id, l.hubspot_deal_id,
           l.hubspot_synced_at
    FROM sales_agent.email_drafts d
    JOIN sales_agent.leads l ON l.id = d.lead_id
    WHERE d.approval_state = 'approved'
      AND NOT EXISTS (
          SELECT 1 FROM sales_agent.email_sends s WHERE s.draft_id = d.id
      )
      AND l.contact_email IS NOT NULL
    ORDER BY d.approved_at ASC NULLS LAST, d.created_at ASC
    LIMIT $1
    """
    out: list[tuple[EmailDraft, Lead]] = []
    async with p.acquire() as conn:
        rows = await conn.fetch(sql, limit)
    for r in rows:
        d = dict(r)
        if d.get("prior_context_ids") is None:
            d["prior_context_ids"] = []
        # asyncpg returns the original keys; Pydantic Lead model keys overlap
        # with EmailDraft so we need to project carefully.
        draft_dict = {
            "id": d["draft_id"], "created_at": d["created_at"],
            "lead_id": d["lead_id"], "recipe_key": d["recipe_key"],
            "subject_variant": d["subject_variant"], "subject": d["subject"],
            "body": d["body"], "model": d["model"],
            "model_input_tokens": d["model_input_tokens"],
            "model_output_tokens": d["model_output_tokens"],
            "model_cost_usd": d["model_cost_usd"],
            "prior_context_ids": d["prior_context_ids"],
            "approval_state": d["approval_state"],
            "approved_by_text": d["approved_by_text"],
            "approved_at": d["approved_at"],
            "edit_request": d["edit_request"],
            "discord_message_id": d["discord_message_id"],
            "discord_channel_id": d["discord_channel_id"],
        }
        lead_dict = {
            "id": d["lead_id_full"], "created_at": d["lead_created"],
            "updated_at": d["updated_at"], "source": d["source"],
            "source_id": d["source_id"], "agco_license": d["agco_license"],
            "business_name": d["business_name"], "address": d["address"],
            "city": d["city"], "province": d["province"],
            "postal_code": d["postal_code"], "lat": d["lat"], "lng": d["lng"],
            "phone": d["phone"], "website_url": d["website_url"],
            "instagram_handle": d["instagram_handle"],
            "contact_email": d["contact_email"],
            "contact_email_source": d["contact_email_source"],
            "contact_email_verified": d["contact_email_verified"],
            "current_site_status": d["current_site_status"],
            "pos_platform": d["pos_platform"],
            "score": d["score"], "status": d["status"],
            "paused_at": d["paused_at"], "paused_reason": d["paused_reason"],
            "notes": d["notes"],
            "hubspot_contact_id": d["hubspot_contact_id"],
            "hubspot_company_id": d["hubspot_company_id"],
            "hubspot_deal_id": d["hubspot_deal_id"],
            "hubspot_synced_at": d["hubspot_synced_at"],
        }
        out.append((EmailDraft.model_validate(draft_dict), Lead.model_validate(lead_dict)))
    return out


async def _send_one(
    draft: EmailDraft, lead: Lead, *,
    lead_repo: LeadRepo, send_repo: SendRepo, unsub_repo: UnsubRepo,
    dry_run: bool,
) -> bool:
    """Returns True on success, False if pre-flight blocked."""
    # Pre-flight: unsubscribed?
    if await unsub_repo.is_unsubscribed(lead.contact_email or ""):
        logger.warning("skip %s: %s is unsubscribed", lead.business_name, lead.contact_email)
        return False

    if dry_run:
        logger.info(
            "[dry-run] would send to %s (%s): %s",
            lead.contact_email, lead.business_name, draft.subject,
        )
        return True

    # Send — provider switch on settings.mail_provider.
    # 'gmail'  → google-api-python-client + SA domain-wide delegation.
    #             Recommended for cold sales: highest Primary placement,
    #             replies thread to operator's Sent folder, looks human.
    # 'resend' → Resend transactional API (kept available for parity /
    #             future transactional flows).
    if settings.mail_provider == "gmail":
        result = await gmail_sender.send_plain(draft=draft, lead=lead)
    else:
        result = await resend_sender.send_plain(draft=draft, lead=lead)

    # Persist the immutable record + link the draft
    send = await send_repo.insert(EmailSendCreate(
        lead_id=lead.id,
        draft_id=draft.id,
        gmail_message_id=result.message_id,   # Resend id stored in this column
        gmail_thread_id=result.thread_id,
        from_email=result.from_email,
        to_email=result.to_email,
        subject=result.subject,
        body=result.body,
        follow_up_seq=0,
    ))

    # Funnel transition
    await lead_repo.transition(
        lead.id, "sent",
        event_type="sent",
        metadata={
            "send_id":          str(send.id),
            "resend_message_id": result.message_id,
            "draft_id":         str(draft.id),
            "recipe_key":       draft.recipe_key,
            "subject_variant":  draft.subject_variant,
        },
    )

    # HubSpot timeline
    try:
        await hub_sync.sync_send(send_repo, lead, send)
    except Exception:
        logger.exception("hubspot.sync_send failed for send=%s — Postgres unaffected", send.id)

    logger.info(
        "✓ sent  %-40s → %-30s  resend=%s",
        lead.business_name[:40], lead.contact_email, result.message_id,
    )
    return True


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="cap on this run (default: respect outreach_daily_cap minus today's count)")
    parser.add_argument("--dry-run", action="store_true",
                        help="run all pre-flight checks but don't actually send")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not settings.resend_api_key:
        raise SystemExit("RESEND_API_KEY not set in .env")
    if not settings.resend_from_email:
        raise SystemExit("RESEND_FROM_EMAIL not set in .env")

    await pool.connect(min_size=1, max_size=4)
    p = pool.pool()
    lead_repo = LeadRepo(p)
    send_repo = SendRepo(p)
    unsub_repo = UnsubRepo(p)

    try:
        # Warm-up cap: how much budget we have left today.
        already_today = await send_repo.daily_count()
        cap = settings.outreach_daily_cap
        budget = max(0, cap - already_today)
        if args.limit is not None:
            budget = min(budget, args.limit)

        if budget <= 0:
            logger.info(
                "warm-up cap exhausted: %d sent today, cap=%d. nothing to do.",
                already_today, cap,
            )
            return

        drafts = await _approved_drafts(p, limit=budget)
        if not drafts:
            logger.info("no approved drafts pending — nothing to send")
            return

        logger.info(
            "sending up to %d email(s)  (today_so_far=%d, cap=%d, dry_run=%s)",
            len(drafts), already_today, cap, args.dry_run,
        )

        sent = 0
        skipped = 0
        for draft, lead in drafts:
            try:
                ok = await _send_one(
                    draft, lead,
                    lead_repo=lead_repo, send_repo=send_repo,
                    unsub_repo=unsub_repo, dry_run=args.dry_run,
                )
            except Exception:
                logger.exception("send failed for draft %s", draft.id)
                skipped += 1
                continue
            if ok:
                sent += 1
            else:
                skipped += 1

        logger.info(
            "done. sent=%d skipped=%d  (today total: %d/%d)",
            sent, skipped, already_today + (sent if not args.dry_run else 0), cap,
        )
    finally:
        await resend_sender.aclose()
        await hub_client.aclose()
        await pool.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
