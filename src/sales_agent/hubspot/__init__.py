"""HubSpot CRM mirror.

Postgres is canonical. After every meaningful state transition the agent
calls a `sync.*` function that pushes the change to HubSpot via raw v3
REST (httpx). Failures log a warning and return — they never roll back the
Postgres write because the operator's CRM is downstream, not in the path.

Public surface:
- `sync.sync_lead(repo, lead)`         — upsert Contact / Company / Deal.
- `sync.sync_send(repo, lead, send)`   — log outbound email engagement.
- `sync.sync_reply(repo, lead, send)`  — log inbound reply + advance stage.
- `pipelines.ensure_pipeline()`        — idempotent bootstrap (one-shot).

The pipeline label comes from `HUBSPOT_PIPELINE_NAME` so future productized
agents (Glitch Trade, Glitch Edge variants) point at their own pipeline in
the same portal without code changes.
"""
