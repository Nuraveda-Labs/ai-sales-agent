-- 2026-04-25 · pos_platform column on leads.
--
-- Replaces the role of `current_site_status` for recipe selection. The
-- old column stays in place (audit trail of the original v1 detector +
-- backward compatibility for any read paths that haven't migrated).
--
-- Enum values reflect the actual Toronto cannabis e-commerce landscape
-- observed across 77 leads:
--   none      — no website at all (or fetch failed)
--   brochure  — apex on Squarespace / Wix / WordPress with no embedded
--                shop or external shop subdomain
--   dutchie   — Dutchie iframe / dedicated dutchie.com storefront
--   blaze     — Blaze POS + ecom (shop.* subdomain pattern, /menu/ paths)
--   tendypos  — TendyPOS via UnoApp (tendy-*.api.unoapp.io)
--   shopify   — Shopify-powered (mostly chains; wrong ICP)
--   custom    — anything else not classifiable into the above
--
-- Apply:
--   psql "$POSTGRES_RW_URL" -v ON_ERROR_STOP=1 -f migrations/0003_pos_platform.sql

BEGIN;

ALTER TABLE sales_agent.leads
    ADD COLUMN IF NOT EXISTS pos_platform TEXT;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'leads_pos_platform_chk'
  ) THEN
    ALTER TABLE sales_agent.leads
      ADD CONSTRAINT leads_pos_platform_chk CHECK (
        pos_platform IS NULL
        OR pos_platform IN ('none','brochure','dutchie','blaze','tendypos','shopify','custom')
      );
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS leads_pos_platform_idx
    ON sales_agent.leads (pos_platform)
    WHERE pos_platform IS NOT NULL;

COMMIT;
