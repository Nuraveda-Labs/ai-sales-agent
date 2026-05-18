# AI Sales Agent

Open-source AI agent for outbound B2B sales — discovery, enrichment,
LLM drafting, human-in-the-loop approval, then send.

## What it does

- **Discovery** — scans a configured region/segment via Google Places to
  build a lead funnel.
- **Enrichment** — pulls company + contact data on each lead, scoring fit.
- **Drafter** — LLM writes a personalised opening cold email per lead,
  marked `pending` in the database.
- **HITL** — pending drafts surface in a Discord channel for approver
  thumbs-up.
- **Sender** — approved drafts are sent through Resend (or any SMTP
  provider) within a configurable time window.

Bounces, unsubscribes, and replies are tracked back to the lead row so
the funnel learns over time.

## Layout

```
src/sales_agent/
  discovery/    # Google Places discovery jobs
  enrichment/   # contact + company enrichment
  agent/        # LLM draft batch runner
  discord/      # HITL bot
  mail/         # Resend / SMTP send runner
  db/           # async DB models + pool
migrations/     # Alembic migrations
playbooks/      # JSON brief templates per outreach play
```

## Install

```
uv pip install -e .
cp .env.example .env   # fill in Google Places + LLM + Resend + Discord keys
alembic upgrade head
```

## License

MIT — see `LICENSE`.
