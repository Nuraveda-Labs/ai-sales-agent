# AI Sales Agent

[![License: MIT](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)
[![Part of Mesh Pilot](https://img.shields.io/badge/Mesh%20Pilot-stack-black.svg)](https://meshpilot.app)
[![Mirrored on Codeberg](https://img.shields.io/badge/codeberg-mirror-black.svg)](https://codeberg.org/Glitch_Exec_Lab/ai-sales-agent)

> **Part of the [Mesh Pilot](https://meshpilot.app) open-source 6-agent marketing stack.**
> Autonomous outbound B2B sales operator — discovery → enrichment → LLM drafting → human-in-the-loop approval → send → learn from outcomes.

The agent builds a lead funnel from public sources, drafts personalised opening emails, and queues every draft for approval before anything leaves your inbox. Replies, bounces, and unsubscribes route back to the lead row so the funnel learns who's worth the next touch.

## Quick start

```bash
git clone https://gitlab.com/mesh-pilot/ai-sales-agent.git
# or: git clone https://codeberg.org/Glitch_Exec_Lab/ai-sales-agent.git
cd ai-sales-agent

uv pip install -e .          # or: pip install -e .
cp .env.example .env         # Google Places + LLM + Resend + Discord keys
alembic upgrade head         # apply migrations

python -m sales_agent.server
```

## What it does

- **Discovery** — scans a configured region/segment via Google Places to build a lead funnel.
- **Enrichment** — pulls company + contact data on each lead, scoring fit.
- **Drafter** — LLM writes a personalised opening cold email per lead, marked `pending` in the database.
- **HITL** — pending drafts surface in a Discord channel for approver thumbs-up. Nothing sends until you click.
- **Sender** — approved drafts go out through Resend (or any SMTP provider) within a configurable time window.
- **Reply tracking** — bounces, unsubscribes, and replies route back to the lead row so the funnel learns over time.

## The HITL pattern (shared across the stack)

Every action that touches money, brand voice, or outbound delivery routes through a human-in-the-loop approval gate. This agent never auto-sends. Drafts land in a queue (Discord by default; the [Mesh Pilot](https://meshpilot.app) cockpit adds a web inbox + Telegram mirrors) and execute only after explicit operator approval. The audit log records who approved what, when, on which channel.

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

## Companions in the stack

| Agent | Domain | Repo |
|---|---|---|
| AI Ads Agent | Meta / Google / TikTok / Amazon Ads | [mesh-pilot/ai-ads-agent](https://gitlab.com/mesh-pilot/ai-ads-agent) |
| **AI Sales Agent** | This repo | — |
| AI Social Agent | Multi-platform posting + ORM | [mesh-pilot/ai-social-agent](https://gitlab.com/mesh-pilot/ai-social-agent) |
| AI UGC Agent | Vertical video ad pipeline | [mesh-pilot/ai-ugc-agent](https://gitlab.com/mesh-pilot/ai-ugc-agent) |
| AI Voice Agent | LiveKit-based phone agent | [mesh-pilot/ai-voice-agent](https://gitlab.com/mesh-pilot/ai-voice-agent) |
| AI SEO Agent | Shopify SEO autopilot | [mesh-pilot/ai-seo-agent](https://gitlab.com/mesh-pilot/ai-seo-agent) |

In production they're orchestrated by **[Mesh Pilot](https://meshpilot.app)** — the closed-source cockpit that runs all six in concert with shared brand context, a single web approval inbox, and cross-agent handoffs.

## Mirrors

- GitLab: [`mesh-pilot/ai-sales-agent`](https://gitlab.com/mesh-pilot/ai-sales-agent)
- Codeberg: [`Glitch_Exec_Lab/ai-sales-agent`](https://codeberg.org/Glitch_Exec_Lab/ai-sales-agent)

## License

[MIT](LICENSE) — fork it, ship products with it, no attribution required.

---

Built by [Glitch Executor Labs](https://glitchexecutor.com).
