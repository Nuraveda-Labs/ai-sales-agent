# Migrations

Raw-SQL migrations applied with `psql`. Numbered `NNNN_<slug>.sql`; apply
in numerical order; never delete or rewrite a committed migration.

Same pattern as [ai_marketing_stack-ads-agent](https://gitlab.com/glitch-grow/ai-ads-agent_marketing_stack-ads-agent/tree/main/migrations).

## Apply

```bash
# All-in-one (idempotent — every CREATE uses IF NOT EXISTS):
psql "$POSTGRES_RW_URL" -v ON_ERROR_STOP=1 -f migrations/0001_init_schema.sql

# Apply every unapplied migration in order:
for f in migrations/[0-9]*.sql; do
  echo "applying $f ..."
  psql "$POSTGRES_RW_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

The role connecting via `POSTGRES_RW_URL` must own (or have CREATE on) the
`sales_agent` schema, and have permission to create the `pgcrypto`,
`vector`, and `pg_trgm` extensions. On a managed Postgres (Cloud SQL,
Supabase, etc.) extensions usually require a one-time enable from the
console — see your provider's docs.

## Conventions

- One transaction per file (`BEGIN; ... COMMIT;`).
- `IF NOT EXISTS` on every `CREATE` so re-running is safe.
- Schema-qualify everything (`sales_agent.<table>`) — no reliance on
  `search_path` outside the migration itself.
- Indexes inline with the table they support, named `<table>_<purpose>_idx`.
- Triggers and functions live in `sales_agent.tg_*` / `sales_agent.fn_*`
  namespaces.
- Migrations are append-only after they ship to production. Schema
  changes go in a new file; never edit a committed one.

## v0001 — initial schema

Tables: `leads`, `email_drafts`, `email_sends`, `lead_events`,
`unsubscribes`, `agent_memory`. Views: `funnel_v`, `recipe_lift_v`,
`daily_send_count_v`. Extensions: `pgcrypto`, `vector`, `pg_trgm`.

See the file header for column-by-column purpose.
