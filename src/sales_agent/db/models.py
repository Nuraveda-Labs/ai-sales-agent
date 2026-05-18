"""Pydantic models for the `sales_agent.*` schema.

Two flavours per row type:
- `<Name>` — full row, what we read out of the DB.
- `<Name>Create` — what callers pass into `repo.insert(...)`. No id, no
  created_at, no defaults the DB fills in.

Funnel-state strings, recipe keys, and current_site_status enums are typed
as `Literal[...]` so call sites can't drift off the schema's CHECK
constraints. If a new state is added in a migration, it lands here and
mypy enforces the rest of the codebase keeps up.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ─── Type aliases ────────────────────────────────────────────────────────────

LeadStatus = Literal[
    "new", "enriched", "scored", "drafted", "sent", "opened", "replied",
    "booked", "paused", "dead",
]

CurrentSiteStatus = Literal["none", "linktree", "builder", "lightspeed", "custom"]

PosPlatform = Literal[
    "none", "brochure", "dutchie", "blaze", "tendypos", "shopify", "custom",
]

Source = Literal["google_places", "agco", "manual"]

ApprovalState = Literal["pending", "approved", "rejected", "edited", "superseded"]

ContactEmailSource = Literal["footer", "ig_bio", "pattern_guess", "reply"]

UnsubVia = Literal["reply_stop", "unsub_link", "manual"]

MemoryKind = Literal["draft", "edit", "reply", "lesson", "rule"]

Outcome = Literal["sent", "opened", "replied", "booked", "dead"]


# ─── Lead ────────────────────────────────────────────────────────────────────

class LeadCreate(BaseModel):
    """What discovery writes into `leads`. Idempotent on (source, source_id)."""

    source: Source
    source_id: str | None = None
    agco_license: str | None = None
    business_name: str
    address: str | None = None
    city: str | None = None
    province: str = "ON"
    postal_code: str | None = None
    lat: float | None = None
    lng: float | None = None
    phone: str | None = None
    website_url: str | None = None
    instagram_handle: str | None = None


class LeadEnrichment(BaseModel):
    """Patch payload written by enrichment workers."""

    contact_email: str | None = None
    contact_email_source: ContactEmailSource | None = None
    contact_email_verified: bool = False
    current_site_status: CurrentSiteStatus | None = None
    pos_platform: PosPlatform | None = None
    instagram_handle: str | None = None
    score: int | None = None


class Lead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime

    source: Source
    source_id: str | None
    agco_license: str | None

    business_name: str
    address: str | None
    city: str | None
    province: str
    postal_code: str | None
    lat: float | None
    lng: float | None

    phone: str | None
    website_url: str | None
    instagram_handle: str | None
    contact_email: str | None
    contact_email_source: ContactEmailSource | None
    contact_email_verified: bool

    current_site_status: CurrentSiteStatus | None
    pos_platform: PosPlatform | None = None

    score: int
    status: LeadStatus
    paused_at: datetime | None
    paused_reason: str | None
    notes: str | None

    # HubSpot mirror (Option A — Postgres canonical, HubSpot downstream)
    hubspot_contact_id: str | None = None
    hubspot_company_id: str | None = None
    hubspot_deal_id: str | None = None
    hubspot_synced_at: datetime | None = None


# ─── Email draft ─────────────────────────────────────────────────────────────

class EmailDraftCreate(BaseModel):
    lead_id: UUID
    recipe_key: str
    subject_variant: str
    subject: str
    body: str
    model: str
    model_input_tokens: int | None = None
    model_output_tokens: int | None = None
    model_cost_usd: float | None = None
    prior_context_ids: list[UUID] = Field(default_factory=list)


class EmailDraft(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    lead_id: UUID
    recipe_key: str
    subject_variant: str
    subject: str
    body: str
    model: str
    model_input_tokens: int | None
    model_output_tokens: int | None
    model_cost_usd: float | None
    prior_context_ids: list[UUID]
    approval_state: ApprovalState
    approved_by_text: str | None
    approved_at: datetime | None
    edit_request: str | None
    discord_message_id: int | None
    discord_channel_id: int | None


# ─── Email send ──────────────────────────────────────────────────────────────

class EmailSendCreate(BaseModel):
    lead_id: UUID
    draft_id: UUID
    gmail_message_id: str
    gmail_thread_id: str
    from_email: str
    to_email: str
    subject: str
    body: str
    follow_up_seq: int = 0


class EmailSend(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    lead_id: UUID
    draft_id: UUID
    gmail_message_id: str
    gmail_thread_id: str
    from_email: str
    to_email: str
    subject: str
    body: str
    tracking_pixel_id: UUID
    sent_at: datetime
    opened_first_at: datetime | None
    opened_count: int
    replied_at: datetime | None
    reply_thread_count: int
    bounced: bool
    unsubscribed: bool
    follow_up_seq: int


# ─── Lead event ──────────────────────────────────────────────────────────────

class LeadEventCreate(BaseModel):
    lead_id: UUID
    event_type: str
    from_status: LeadStatus | None = None
    to_status: LeadStatus | None = None
    actor: str = "agent"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ─── Unsubscribe ─────────────────────────────────────────────────────────────

class Unsubscribe(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: str
    unsubscribed_at: datetime
    via: UnsubVia
    lead_id: UUID | None
    notes: str | None


# ─── Agent memory ────────────────────────────────────────────────────────────

class AgentMemoryCreate(BaseModel):
    lead_id: UUID | None = None
    kind: MemoryKind
    recipe_key: str | None = None
    content: str
    embedding: list[float] | None = None  # pgvector adapter handles serialization
    outcome: Outcome | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentMemory(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    lead_id: UUID | None
    kind: MemoryKind
    recipe_key: str | None
    content: str
    embedding: list[float] | None
    outcome: Outcome | None
    metadata: dict[str, Any]


# ─── Aggregates ──────────────────────────────────────────────────────────────

class FunnelSnapshot(BaseModel):
    """One row from sales_agent.funnel_v."""

    status: LeadStatus
    lead_count: int
    lead_count_7d: int
    lead_count_24h: int


class RecipeLift(BaseModel):
    """One row from sales_agent.recipe_lift_v."""

    recipe_key: str
    subject_variant: str
    sent_count: int
    opened_count: int
    replied_count: int
    open_rate_pct: float | None
    reply_rate_pct: float | None
