-- 2026-04-25 · Initial sales_agent schema.
--
-- Tables:
--   sales_agent.leads          — every prospect, with enrichment + funnel state
--   sales_agent.email_drafts   — every drafted email (recipe + subject + LLM telemetry + approval state)
--   sales_agent.email_sends    — every actual outbound (Gmail ids + open/reply tracking)
--   sales_agent.lead_events    — append-only state-transition log
--   sales_agent.unsubscribes   — CASL "stop" list, never email these addresses again
--   sales_agent.agent_memory   — hybrid (pgvector + tsvector) decision log feeding <prior_context>
--
-- Views:
--   sales_agent.funnel_v       — funnel snapshot for /leads stats
--   sales_agent.recipe_lift_v  — per-recipe + per-subject open / reply rates
--
-- Apply with the rw role:
--   psql "$POSTGRES_RW_URL" -v ON_ERROR_STOP=1 -f migrations/0001_init_schema.sql

BEGIN;

-- ─── Extensions ──────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector embeddings
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- fuzzy business-name match

CREATE SCHEMA IF NOT EXISTS sales_agent;
SET search_path TO sales_agent, public;

-- ─── updated_at trigger fn ───────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION sales_agent.tg_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ─── leads ───────────────────────────────────────────────────────────────────
-- Every prospect ever seen. Source-deduped on (source, source_id) so re-running
-- discovery is idempotent.
CREATE TABLE IF NOT EXISTS sales_agent.leads (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Source attribution
    source                   TEXT NOT NULL,             -- 'google_places' | 'agco' | 'manual'
    source_id                TEXT,                      -- e.g., Google Place ID
    agco_license             TEXT,                      -- AGCO Cannabis Retail Store licence #

    -- Identity
    business_name            TEXT NOT NULL,
    address                  TEXT,
    city                     TEXT,
    province                 TEXT NOT NULL DEFAULT 'ON',
    postal_code              TEXT,
    lat                      NUMERIC(9,6),
    lng                      NUMERIC(9,6),

    -- Contact
    phone                    TEXT,
    website_url              TEXT,
    instagram_handle         TEXT,
    contact_email            TEXT,
    contact_email_source     TEXT,                      -- 'footer' | 'ig_bio' | 'pattern_guess' | 'reply'
    contact_email_verified   BOOLEAN NOT NULL DEFAULT false,

    -- Enrichment
    current_site_status      TEXT,                      -- 'none' | 'linktree' | 'builder' | 'lightspeed' | 'custom'

    -- Funnel
    score                    INTEGER NOT NULL DEFAULT 0,
    status                   TEXT NOT NULL DEFAULT 'new',
    paused_at                TIMESTAMPTZ,
    paused_reason            TEXT,
    notes                    TEXT,

    CONSTRAINT leads_source_id_uq UNIQUE (source, source_id),
    CONSTRAINT leads_status_chk CHECK (status IN
        ('new','enriched','scored','drafted','sent','opened','replied','booked','paused','dead')),
    CONSTRAINT leads_site_status_chk CHECK (
        current_site_status IS NULL
        OR current_site_status IN ('none','linktree','builder','lightspeed','custom')
    )
);

CREATE INDEX IF NOT EXISTS leads_status_idx
    ON sales_agent.leads (status);
CREATE INDEX IF NOT EXISTS leads_site_status_idx
    ON sales_agent.leads (current_site_status)
    WHERE current_site_status IS NOT NULL;
CREATE INDEX IF NOT EXISTS leads_score_idx
    ON sales_agent.leads (score DESC)
    WHERE status IN ('enriched','scored');
CREATE INDEX IF NOT EXISTS leads_business_name_trgm
    ON sales_agent.leads USING GIN (business_name gin_trgm_ops);

DROP TRIGGER IF EXISTS leads_updated_at ON sales_agent.leads;
CREATE TRIGGER leads_updated_at
    BEFORE UPDATE ON sales_agent.leads
    FOR EACH ROW EXECUTE FUNCTION sales_agent.tg_set_updated_at();


-- ─── email_drafts ────────────────────────────────────────────────────────────
-- Every draft an LLM produced for a lead. Multiple drafts per lead are
-- expected (subject A/B + post-edit revisions). approval_state tracks the
-- HITL outcome.
CREATE TABLE IF NOT EXISTS sales_agent.email_drafts (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    lead_id                  UUID NOT NULL REFERENCES sales_agent.leads(id) ON DELETE CASCADE,

    -- Recipe + subject
    recipe_key               TEXT NOT NULL,             -- maps to RECIPES key in playbook
    subject_variant          TEXT NOT NULL,             -- the chosen subject template
    subject                  TEXT NOT NULL,             -- fully rendered subject
    body                     TEXT NOT NULL,             -- fully rendered body (no CASL footer yet)

    -- LLM telemetry
    model                    TEXT NOT NULL,
    model_input_tokens       INTEGER,
    model_output_tokens      INTEGER,
    model_cost_usd           NUMERIC(10,6),
    prior_context_ids        UUID[],                    -- agent_memory rows that fed this draft

    -- Approval state
    approval_state           TEXT NOT NULL DEFAULT 'pending',
    approved_by_text         TEXT,                      -- 'discord:123456789'
    approved_at              TIMESTAMPTZ,
    edit_request             TEXT,                      -- operator's edit instructions
    discord_message_id       BIGINT,
    discord_channel_id       BIGINT,

    CONSTRAINT email_drafts_state_chk CHECK (approval_state IN
        ('pending','approved','rejected','edited','superseded'))
);

CREATE INDEX IF NOT EXISTS email_drafts_lead_idx
    ON sales_agent.email_drafts (lead_id);
CREATE INDEX IF NOT EXISTS email_drafts_pending_idx
    ON sales_agent.email_drafts (created_at DESC)
    WHERE approval_state = 'pending';
CREATE INDEX IF NOT EXISTS email_drafts_discord_msg_idx
    ON sales_agent.email_drafts (discord_message_id)
    WHERE discord_message_id IS NOT NULL;


-- ─── email_sends ─────────────────────────────────────────────────────────────
-- The immutable record of what actually went out the door. Snapshots
-- subject + body so even if the draft is later deleted, the sent payload
-- is preserved for audit / CASL / dispute resolution.
CREATE TABLE IF NOT EXISTS sales_agent.email_sends (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    lead_id                  UUID NOT NULL REFERENCES sales_agent.leads(id) ON DELETE CASCADE,
    draft_id                 UUID NOT NULL REFERENCES sales_agent.email_drafts(id),

    -- Gmail
    gmail_message_id         TEXT NOT NULL,
    gmail_thread_id          TEXT NOT NULL,

    -- Snapshot of what was sent
    from_email               TEXT NOT NULL,
    to_email                 TEXT NOT NULL,
    subject                  TEXT NOT NULL,
    body                     TEXT NOT NULL,

    -- Tracking
    tracking_pixel_id        UUID NOT NULL DEFAULT gen_random_uuid(),
    sent_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    opened_first_at          TIMESTAMPTZ,
    opened_count             INTEGER NOT NULL DEFAULT 0,
    replied_at               TIMESTAMPTZ,
    reply_thread_count       INTEGER NOT NULL DEFAULT 0,
    bounced                  BOOLEAN NOT NULL DEFAULT false,
    unsubscribed             BOOLEAN NOT NULL DEFAULT false,

    -- Sequence position
    follow_up_seq            INTEGER NOT NULL DEFAULT 0,   -- 0=initial, 1=4day, 2=10day

    CONSTRAINT email_sends_pixel_uq UNIQUE (tracking_pixel_id),
    CONSTRAINT email_sends_gmail_uq UNIQUE (gmail_message_id),
    CONSTRAINT email_sends_followup_chk CHECK (follow_up_seq >= 0 AND follow_up_seq <= 5)
);

CREATE INDEX IF NOT EXISTS email_sends_lead_idx
    ON sales_agent.email_sends (lead_id);
CREATE INDEX IF NOT EXISTS email_sends_thread_idx
    ON sales_agent.email_sends (gmail_thread_id);
CREATE INDEX IF NOT EXISTS email_sends_sent_at_idx
    ON sales_agent.email_sends (sent_at DESC);
CREATE INDEX IF NOT EXISTS email_sends_no_reply_idx
    ON sales_agent.email_sends (sent_at)
    WHERE replied_at IS NULL AND bounced = false AND unsubscribed = false;


-- ─── lead_events ─────────────────────────────────────────────────────────────
-- Append-only state-transition log. Never UPDATE; only INSERT. Drives
-- /leads stats and the per-lead activity timeline in Discord.
CREATE TABLE IF NOT EXISTS sales_agent.lead_events (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    lead_id                  UUID NOT NULL REFERENCES sales_agent.leads(id) ON DELETE CASCADE,
    event_type               TEXT NOT NULL,
    from_status              TEXT,
    to_status                TEXT,
    actor                    TEXT NOT NULL,             -- 'agent' | 'discord:<id>'
    metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS lead_events_lead_idx
    ON sales_agent.lead_events (lead_id, created_at DESC);
CREATE INDEX IF NOT EXISTS lead_events_type_idx
    ON sales_agent.lead_events (event_type);


-- ─── unsubscribes ────────────────────────────────────────────────────────────
-- CASL hard-stop list. Pre-flight check before any send: if to_email is here,
-- the send is blocked. Never delete rows from this table.
CREATE TABLE IF NOT EXISTS sales_agent.unsubscribes (
    email                    TEXT PRIMARY KEY,
    unsubscribed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    via                      TEXT NOT NULL,             -- 'reply_stop' | 'unsub_link' | 'manual'
    lead_id                  UUID REFERENCES sales_agent.leads(id) ON DELETE SET NULL,
    notes                    TEXT
);


-- ─── agent_memory ────────────────────────────────────────────────────────────
-- Hybrid (semantic + FTS) decision log. Every draft / edit / reply / lesson
-- gets a row; the drafter's <prior_context> is built by retrieving relevant
-- rows on each new lead. Mirror of ads_agent.agent_memory.
CREATE TABLE IF NOT EXISTS sales_agent.agent_memory (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    lead_id                  UUID REFERENCES sales_agent.leads(id) ON DELETE SET NULL,
    kind                     TEXT NOT NULL,             -- 'draft'|'edit'|'reply'|'lesson'|'rule'
    recipe_key               TEXT,
    content                  TEXT NOT NULL,
    embedding                vector(1536),              -- nullable; populated async by embed worker
    content_tsv              tsvector GENERATED ALWAYS AS
                                 (to_tsvector('english', content)) STORED,
    outcome                  TEXT,                      -- 'sent'|'opened'|'replied'|'booked'|'dead'
    metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT agent_memory_kind_chk CHECK (kind IN
        ('draft','edit','reply','lesson','rule'))
);

CREATE INDEX IF NOT EXISTS agent_memory_lead_idx
    ON sales_agent.agent_memory (lead_id, created_at DESC)
    WHERE lead_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS agent_memory_kind_idx
    ON sales_agent.agent_memory (kind);
CREATE INDEX IF NOT EXISTS agent_memory_recipe_idx
    ON sales_agent.agent_memory (recipe_key)
    WHERE recipe_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS agent_memory_tsv_idx
    ON sales_agent.agent_memory USING GIN (content_tsv);
-- HNSW index on the embedding column. Cosine distance matches the embedding
-- model's training objective. Tune (m, ef_construction) once volume justifies.
CREATE INDEX IF NOT EXISTS agent_memory_embedding_hnsw
    ON sales_agent.agent_memory
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- ─── views ───────────────────────────────────────────────────────────────────

-- Funnel snapshot — backs the /leads stats Discord command.
CREATE OR REPLACE VIEW sales_agent.funnel_v AS
SELECT
    status,
    COUNT(*) AS lead_count,
    COUNT(*) FILTER (WHERE created_at > now() - INTERVAL '7 days')  AS lead_count_7d,
    COUNT(*) FILTER (WHERE created_at > now() - INTERVAL '24 hours') AS lead_count_24h
FROM sales_agent.leads
GROUP BY status;

-- Per-recipe + per-subject lift. Backs /recipes lift.
CREATE OR REPLACE VIEW sales_agent.recipe_lift_v AS
SELECT
    d.recipe_key,
    d.subject_variant,
    COUNT(s.id)                                                        AS sent_count,
    COUNT(s.opened_first_at)                                           AS opened_count,
    COUNT(s.replied_at)                                                AS replied_count,
    ROUND(COUNT(s.opened_first_at)::numeric
          / NULLIF(COUNT(s.id), 0) * 100, 1)                           AS open_rate_pct,
    ROUND(COUNT(s.replied_at)::numeric
          / NULLIF(COUNT(s.id), 0) * 100, 1)                           AS reply_rate_pct
FROM sales_agent.email_drafts d
JOIN sales_agent.email_sends  s ON s.draft_id = d.id
WHERE s.bounced = false
  AND s.unsubscribed = false
  AND s.follow_up_seq = 0   -- initial sends only; follow-ups skew open rates
GROUP BY d.recipe_key, d.subject_variant;

-- Daily send volume — used by the warm-up cap enforcer before each send.
CREATE OR REPLACE VIEW sales_agent.daily_send_count_v AS
SELECT
    date_trunc('day', sent_at AT TIME ZONE 'America/Toronto')::date AS day,
    COUNT(*) AS sent
FROM sales_agent.email_sends
GROUP BY day;

COMMIT;
