-- 2026-04-25 · HubSpot CRM mirror — link columns on leads + email_sends.
--
-- Postgres remains canonical (decision: Option A, one-way mirror). These
-- columns let us re-resolve HubSpot Contact / Company / Deal / Engagement
-- objects we've already created so re-runs of sync are idempotent and we
-- never duplicate records in the operator's CRM.
--
-- Apply:
--   psql "$POSTGRES_RW_URL" -v ON_ERROR_STOP=1 -f migrations/0002_hubspot_links.sql

BEGIN;

ALTER TABLE sales_agent.leads
    ADD COLUMN IF NOT EXISTS hubspot_contact_id TEXT,
    ADD COLUMN IF NOT EXISTS hubspot_company_id TEXT,
    ADD COLUMN IF NOT EXISTS hubspot_deal_id    TEXT,
    ADD COLUMN IF NOT EXISTS hubspot_synced_at  TIMESTAMPTZ;

-- Re-resolution lookups: "given a HubSpot id from a webhook, find the lead".
CREATE INDEX IF NOT EXISTS leads_hubspot_contact_idx
    ON sales_agent.leads (hubspot_contact_id)
    WHERE hubspot_contact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS leads_hubspot_deal_idx
    ON sales_agent.leads (hubspot_deal_id)
    WHERE hubspot_deal_id IS NOT NULL;

-- Logged engagement id on each send so reply / open updates land on the
-- right HubSpot timeline entry.
ALTER TABLE sales_agent.email_sends
    ADD COLUMN IF NOT EXISTS hubspot_engagement_id TEXT;

COMMIT;
