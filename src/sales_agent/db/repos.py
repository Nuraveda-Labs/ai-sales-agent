"""Async repos — one class per table.

Every method is small, type-annotated, and only reads/writes one logical
unit. No business logic in this module — call sites compose. Funnel-state
transitions go through `LeadRepo.transition` so the lead_event log stays
in lockstep with `leads.status`.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from sales_agent.db.models import (
    AgentMemory,
    AgentMemoryCreate,
    EmailDraft,
    EmailDraftCreate,
    EmailSend,
    EmailSendCreate,
    FunnelSnapshot,
    Lead,
    LeadCreate,
    LeadEnrichment,
    LeadEventCreate,
    LeadStatus,
    RecipeLift,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _to_lead(r: asyncpg.Record) -> Lead:
    return Lead.model_validate(dict(r))


def _to_draft(r: asyncpg.Record) -> EmailDraft:
    d = dict(r)
    # asyncpg returns UUID[] as list[UUID], but a NULL column comes back as
    # None — coerce so Pydantic's `list[UUID]` validator doesn't reject it.
    if d.get("prior_context_ids") is None:
        d["prior_context_ids"] = []
    return EmailDraft.model_validate(d)


def _to_send(r: asyncpg.Record) -> EmailSend:
    return EmailSend.model_validate(dict(r))


def _to_memory(r: asyncpg.Record) -> AgentMemory:
    d = dict(r)
    # metadata comes back as a JSON string from asyncpg by default; coerce.
    if isinstance(d.get("metadata"), str):
        d["metadata"] = json.loads(d["metadata"])
    return AgentMemory.model_validate(d)


_LEAD_COLS = """
    id, created_at, updated_at,
    source, source_id, agco_license,
    business_name, address, city, province, postal_code, lat, lng,
    phone, website_url, instagram_handle, contact_email,
    contact_email_source, contact_email_verified,
    current_site_status, pos_platform,
    score, status, paused_at, paused_reason, notes,
    hubspot_contact_id, hubspot_company_id, hubspot_deal_id, hubspot_synced_at
"""

_DRAFT_COLS = """
    id, created_at, lead_id,
    recipe_key, subject_variant, subject, body,
    model, model_input_tokens, model_output_tokens, model_cost_usd,
    prior_context_ids,
    approval_state, approved_by_text, approved_at, edit_request,
    discord_message_id, discord_channel_id
"""

_SEND_COLS = """
    id, created_at, lead_id, draft_id,
    gmail_message_id, gmail_thread_id,
    from_email, to_email, subject, body,
    tracking_pixel_id, sent_at,
    opened_first_at, opened_count,
    replied_at, reply_thread_count,
    bounced, unsubscribed, follow_up_seq
"""

_MEM_COLS = """
    id, created_at, lead_id, kind, recipe_key,
    content, embedding, outcome, metadata
"""


# ─── LeadRepo ────────────────────────────────────────────────────────────────


class LeadRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert(self, payload: LeadCreate) -> Lead:
        """Insert or update on (source, source_id). Idempotent for re-runs of discovery."""
        sql = f"""
        INSERT INTO sales_agent.leads (
            source, source_id, agco_license,
            business_name, address, city, province, postal_code, lat, lng,
            phone, website_url, instagram_handle
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        ON CONFLICT (source, source_id) DO UPDATE SET
            -- Only refresh fields when discovery has new info; never null-clobber.
            agco_license     = COALESCE(EXCLUDED.agco_license,     sales_agent.leads.agco_license),
            business_name    = EXCLUDED.business_name,
            address          = COALESCE(EXCLUDED.address,          sales_agent.leads.address),
            city             = COALESCE(EXCLUDED.city,             sales_agent.leads.city),
            province         = EXCLUDED.province,
            postal_code      = COALESCE(EXCLUDED.postal_code,      sales_agent.leads.postal_code),
            lat              = COALESCE(EXCLUDED.lat,              sales_agent.leads.lat),
            lng              = COALESCE(EXCLUDED.lng,              sales_agent.leads.lng),
            phone            = COALESCE(EXCLUDED.phone,            sales_agent.leads.phone),
            website_url      = COALESCE(EXCLUDED.website_url,      sales_agent.leads.website_url),
            instagram_handle = COALESCE(EXCLUDED.instagram_handle, sales_agent.leads.instagram_handle)
        RETURNING {_LEAD_COLS}
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                sql,
                payload.source, payload.source_id, payload.agco_license,
                payload.business_name, payload.address, payload.city,
                payload.province, payload.postal_code, payload.lat, payload.lng,
                payload.phone, payload.website_url, payload.instagram_handle,
            )
        assert row is not None
        return _to_lead(row)

    async def get(self, lead_id: UUID) -> Lead | None:
        sql = f"SELECT {_LEAD_COLS} FROM sales_agent.leads WHERE id = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, lead_id)
        return _to_lead(row) if row else None

    async def by_status(self, status: LeadStatus, limit: int = 100) -> list[Lead]:
        sql = f"""
        SELECT {_LEAD_COLS} FROM sales_agent.leads
        WHERE status = $1
        ORDER BY score DESC, created_at ASC
        LIMIT $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, status, limit)
        return [_to_lead(r) for r in rows]

    async def update_enrichment(self, lead_id: UUID, patch: LeadEnrichment) -> Lead:
        """Patch enrichment fields; only sets non-None values (no null-clobber)."""
        sql = f"""
        UPDATE sales_agent.leads SET
            contact_email          = COALESCE($2, contact_email),
            contact_email_source   = COALESCE($3, contact_email_source),
            contact_email_verified = COALESCE($4, contact_email_verified),
            current_site_status    = COALESCE($5, current_site_status),
            pos_platform           = COALESCE($6, pos_platform),
            instagram_handle       = COALESCE($7, instagram_handle),
            score                  = COALESCE($8, score)
        WHERE id = $1
        RETURNING {_LEAD_COLS}
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                sql, lead_id,
                patch.contact_email, patch.contact_email_source,
                patch.contact_email_verified if patch.contact_email else None,
                patch.current_site_status, patch.pos_platform,
                patch.instagram_handle, patch.score,
            )
        if row is None:
            raise LookupError(f"lead {lead_id} not found")
        return _to_lead(row)

    async def transition(
        self,
        lead_id: UUID,
        to_status: LeadStatus,
        *,
        actor: str = "agent",
        event_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Lead:
        """Move a lead to a new status and write the matching lead_event row in one tx."""
        async with self._pool.acquire() as conn, conn.transaction():
            cur = await conn.fetchrow(
                "SELECT status FROM sales_agent.leads WHERE id = $1 FOR UPDATE",
                lead_id,
            )
            if cur is None:
                raise LookupError(f"lead {lead_id} not found")
            from_status = cur["status"]

            row = await conn.fetchrow(
                f"UPDATE sales_agent.leads SET status = $1 WHERE id = $2 RETURNING {_LEAD_COLS}",
                to_status, lead_id,
            )
            await conn.execute(
                """
                INSERT INTO sales_agent.lead_events
                    (lead_id, event_type, from_status, to_status, actor, metadata)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                lead_id, event_type or f"transition:{to_status}",
                from_status, to_status, actor, json.dumps(metadata or {}),
            )
        assert row is not None
        return _to_lead(row)

    async def pause(self, lead_id: UUID, reason: str, *, actor: str = "agent") -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE sales_agent.leads
                SET status = 'paused', paused_at = now(), paused_reason = $2
                WHERE id = $1
                """,
                lead_id, reason,
            )
            await conn.execute(
                """
                INSERT INTO sales_agent.lead_events
                    (lead_id, event_type, to_status, actor, metadata)
                VALUES ($1, 'paused', 'paused', $2, jsonb_build_object('reason', $3::text))
                """,
                lead_id, actor, reason,
            )

    async def set_hubspot_ids(
        self,
        lead_id: UUID,
        *,
        contact_id: str | None,
        company_id: str | None,
        deal_id: str | None,
        synced_at: Any,
    ) -> Lead:
        """Persist the HubSpot mirror ids back to leads after a successful sync.

        Uses COALESCE so we don't blow away an existing id when the sync layer
        only resolved one of the three (e.g. company succeeded but contact had
        no email yet).
        """
        sql = f"""
        UPDATE sales_agent.leads SET
            hubspot_contact_id = COALESCE($2, hubspot_contact_id),
            hubspot_company_id = COALESCE($3, hubspot_company_id),
            hubspot_deal_id    = COALESCE($4, hubspot_deal_id),
            hubspot_synced_at  = $5
        WHERE id = $1
        RETURNING {_LEAD_COLS}
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                sql, lead_id, contact_id, company_id, deal_id, synced_at,
            )
        if row is None:
            raise LookupError(f"lead {lead_id} not found")
        return _to_lead(row)

    async def funnel(self) -> list[FunnelSnapshot]:
        sql = "SELECT status, lead_count, lead_count_7d, lead_count_24h FROM sales_agent.funnel_v"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return [FunnelSnapshot.model_validate(dict(r)) for r in rows]


# ─── DraftRepo ───────────────────────────────────────────────────────────────


class DraftRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def insert(self, payload: EmailDraftCreate) -> EmailDraft:
        """Insert a new draft. Any prior `pending` drafts for the same lead
        are auto-superseded in the same transaction, so the operator's
        approval queue always shows one pending draft per lead."""
        sql = f"""
        INSERT INTO sales_agent.email_drafts (
            lead_id, recipe_key, subject_variant, subject, body,
            model, model_input_tokens, model_output_tokens, model_cost_usd,
            prior_context_ids
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        RETURNING {_DRAFT_COLS}
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE sales_agent.email_drafts
                SET approval_state = 'superseded'
                WHERE lead_id = $1 AND approval_state = 'pending'
                """,
                payload.lead_id,
            )
            row = await conn.fetchrow(
                sql,
                payload.lead_id, payload.recipe_key, payload.subject_variant,
                payload.subject, payload.body,
                payload.model, payload.model_input_tokens, payload.model_output_tokens,
                payload.model_cost_usd, payload.prior_context_ids or None,
            )
        assert row is not None
        return _to_draft(row)

    async def get(self, draft_id: UUID) -> EmailDraft | None:
        sql = f"SELECT {_DRAFT_COLS} FROM sales_agent.email_drafts WHERE id = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, draft_id)
        return _to_draft(row) if row else None

    async def pending(self, limit: int = 50) -> list[EmailDraft]:
        sql = f"""
        SELECT {_DRAFT_COLS} FROM sales_agent.email_drafts
        WHERE approval_state = 'pending'
        ORDER BY created_at ASC
        LIMIT $1
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, limit)
        return [_to_draft(r) for r in rows]

    async def by_discord_message(self, discord_message_id: int) -> EmailDraft | None:
        sql = f"""
        SELECT {_DRAFT_COLS} FROM sales_agent.email_drafts
        WHERE discord_message_id = $1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, discord_message_id)
        return _to_draft(row) if row else None

    async def attach_discord(
        self, draft_id: UUID, *, channel_id: int, message_id: int,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sales_agent.email_drafts
                SET discord_channel_id = $2, discord_message_id = $3
                WHERE id = $1
                """,
                draft_id, channel_id, message_id,
            )

    async def mark_approved(self, draft_id: UUID, *, approver: str) -> EmailDraft:
        return await self._mark_state(draft_id, "approved", approver=approver)

    async def mark_rejected(self, draft_id: UUID, *, approver: str) -> EmailDraft:
        return await self._mark_state(draft_id, "rejected", approver=approver)

    async def mark_edit_requested(
        self, draft_id: UUID, *, approver: str, edit_request: str,
    ) -> EmailDraft:
        return await self._mark_state(
            draft_id, "edited", approver=approver, edit_request=edit_request,
        )

    async def _mark_state(
        self, draft_id: UUID, state: str, *,
        approver: str, edit_request: str | None = None,
    ) -> EmailDraft:
        sql = f"""
        UPDATE sales_agent.email_drafts SET
            approval_state   = $2,
            approved_by_text = $3,
            approved_at      = now(),
            edit_request     = COALESCE($4, edit_request)
        WHERE id = $1 AND approval_state = 'pending'
        RETURNING {_DRAFT_COLS}
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, draft_id, state, approver, edit_request)
        if row is None:
            raise LookupError(f"draft {draft_id} not pending or not found")
        return _to_draft(row)


# ─── SendRepo ────────────────────────────────────────────────────────────────


class SendRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def insert(self, payload: EmailSendCreate) -> EmailSend:
        sql = f"""
        INSERT INTO sales_agent.email_sends (
            lead_id, draft_id,
            gmail_message_id, gmail_thread_id,
            from_email, to_email, subject, body,
            follow_up_seq
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        RETURNING {_SEND_COLS}
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                sql,
                payload.lead_id, payload.draft_id,
                payload.gmail_message_id, payload.gmail_thread_id,
                payload.from_email, payload.to_email,
                payload.subject, payload.body,
                payload.follow_up_seq,
            )
        assert row is not None
        return _to_send(row)

    async def by_pixel(self, pixel_id: UUID) -> EmailSend | None:
        sql = f"SELECT {_SEND_COLS} FROM sales_agent.email_sends WHERE tracking_pixel_id = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, pixel_id)
        return _to_send(row) if row else None

    async def by_thread(self, thread_id: str) -> EmailSend | None:
        sql = f"""
        SELECT {_SEND_COLS} FROM sales_agent.email_sends
        WHERE gmail_thread_id = $1
        ORDER BY sent_at DESC
        LIMIT 1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, thread_id)
        return _to_send(row) if row else None

    async def record_open(self, pixel_id: UUID) -> None:
        """Increment open count + set first-open if unset. Idempotent under reload."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sales_agent.email_sends SET
                    opened_first_at = COALESCE(opened_first_at, now()),
                    opened_count    = opened_count + 1
                WHERE tracking_pixel_id = $1
                """,
                pixel_id,
            )

    async def record_reply(self, thread_id: str) -> EmailSend | None:
        """Mark a thread as having received a reply. Returns the updated row."""
        sql = f"""
        UPDATE sales_agent.email_sends SET
            replied_at         = COALESCE(replied_at, now()),
            reply_thread_count = reply_thread_count + 1
        WHERE gmail_thread_id = $1
        RETURNING {_SEND_COLS}
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, thread_id)
        return _to_send(row) if row else None

    async def set_hubspot_engagement(self, send_id: UUID, engagement_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sales_agent.email_sends
                SET hubspot_engagement_id = $2
                WHERE id = $1
                """,
                send_id, engagement_id,
            )

    async def daily_count(self) -> int:
        """Count of initial-send emails sent today (<region> local). Excludes follow-ups
        from the warm-up cap because follow-ups don't damage reputation the way new
        cold-thread sends do."""
        async with self._pool.acquire() as conn:
            v = await conn.fetchval(
                """
                SELECT COUNT(*) FROM sales_agent.email_sends
                WHERE follow_up_seq = 0
                  AND date_trunc('day', sent_at AT TIME ZONE 'America/<region>')
                    = date_trunc('day', now()      AT TIME ZONE 'America/<region>')
                """
            )
        return int(v or 0)

    async def recipe_lift(self) -> list[RecipeLift]:
        sql = """
        SELECT recipe_key, subject_variant, sent_count, opened_count, replied_count,
               open_rate_pct, reply_rate_pct
        FROM sales_agent.recipe_lift_v
        ORDER BY sent_count DESC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return [RecipeLift.model_validate(dict(r)) for r in rows]


# ─── EventRepo ───────────────────────────────────────────────────────────────


class EventRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def log(self, payload: LeadEventCreate) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sales_agent.lead_events
                    (lead_id, event_type, from_status, to_status, actor, metadata)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                payload.lead_id, payload.event_type,
                payload.from_status, payload.to_status,
                payload.actor, json.dumps(payload.metadata),
            )


# ─── UnsubRepo ───────────────────────────────────────────────────────────────


class UnsubRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def is_unsubscribed(self, email: str) -> bool:
        async with self._pool.acquire() as conn:
            v = await conn.fetchval(
                "SELECT 1 FROM sales_agent.unsubscribes WHERE email = $1",
                email.lower(),
            )
        return v is not None

    async def add(
        self, email: str, *, via: str, lead_id: UUID | None = None,
        notes: str | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sales_agent.unsubscribes (email, via, lead_id, notes)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (email) DO NOTHING
                """,
                email.lower(), via, lead_id, notes,
            )


# ─── MemoryRepo ──────────────────────────────────────────────────────────────


class MemoryRepo:
    """Decision log + hybrid (semantic + FTS) recall.

    `recall_for_lead` is wired but kept simple: returns the N most-recent
    rows for that lead, optionally filtered by recipe_key. The vector +
    FTS hybrid retrieval lands once the embedding worker is online and we
    have at least a few hundred rows to make the recall worth doing.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def insert(self, payload: AgentMemoryCreate) -> AgentMemory:
        sql = f"""
        INSERT INTO sales_agent.agent_memory
            (lead_id, kind, recipe_key, content, embedding, outcome, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        RETURNING {_MEM_COLS}
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                sql,
                payload.lead_id, payload.kind, payload.recipe_key,
                payload.content, payload.embedding, payload.outcome,
                json.dumps(payload.metadata),
            )
        assert row is not None
        mem = _to_memory(row)
        # Brain mirror (GROW-BIND-2): also report the write to
        # brain-mcp so sibling agents on the same brand can see
        # what Sales just did via team_state / recent_activity /
        # briefing. Silently no-ops when BSK-003 isn't configured for
        # the current SALES_AGENT_BRAND_SLUG.
        from sales_agent.brain import schedule_brain_mirror
        schedule_brain_mirror(
            kind=payload.kind,
            content=payload.content,
            lead_id=str(payload.lead_id) if payload.lead_id is not None else None,
            recipe_key=payload.recipe_key,
            outcome=payload.outcome,
            metadata=payload.metadata,
        )
        return mem

    async def recall_for_lead(
        self, lead_id: UUID, *, limit: int = 10,
        recipe_key: str | None = None,
    ) -> list[AgentMemory]:
        sql = f"""
        SELECT {_MEM_COLS} FROM sales_agent.agent_memory
        WHERE lead_id = $1
          AND ($2::text IS NULL OR recipe_key = $2)
        ORDER BY created_at DESC
        LIMIT $3
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, lead_id, recipe_key, limit)
        return [_to_memory(r) for r in rows]

    async def recall_by_recipe(
        self, recipe_key: str, *, limit: int = 20,
        outcome: str | None = None,
    ) -> list[AgentMemory]:
        """Recipe-scoped recall — used by the drafter to ground prompts in
        what worked / failed for similar shops."""
        sql = f"""
        SELECT {_MEM_COLS} FROM sales_agent.agent_memory
        WHERE recipe_key = $1
          AND ($2::text IS NULL OR outcome = $2)
        ORDER BY created_at DESC
        LIMIT $3
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, recipe_key, outcome, limit)
        return [_to_memory(r) for r in rows]
