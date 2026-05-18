# Changelog

## [0.1.0] — 2026-05-18

### Added

- Initial open-source release of the AI sales agent engine.
- Discovery → enrichment → draft → HITL → send pipeline.
- Alembic-managed Postgres schema.
- Discord-based human approval gateway.
- Resend mail sender (SMTP adapter pluggable).
- Playbook system for swappable outreach plays.

### Removed (extracted to a separate proprietary repo)

- Brand-specific outreach templates and brand directory.
- Region-specific discovery queries.
- Fine-tuned drafter prompts.
