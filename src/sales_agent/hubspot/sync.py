"""Public sync surface — the only module agent nodes should import.

Each entry point is fire-and-forget: HubSpot failures are logged and
swallowed so the Postgres write (which already happened) is not unwound.
Postgres remains canonical.

Sync calls are gated by `settings.hubspot_sync_enabled` so dev runs and
CI don't spam the production portal.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sales_agent.config import settings
from sales_agent.db.models import EmailSend, Lead
from sales_agent.db.repos import LeadRepo, SendRepo
from sales_agent.hubspot import client, mapper, pipelines
from sales_agent.hubspot.stages import STATUS_TO_STAGE_LABEL

logger = logging.getLogger(__name__)


# Cache the pipeline + stage ids per process — they don't change at runtime.
_pipeline_id: str | None = None
_stage_id_cache: dict[str, str] = {}


async def _resolve_pipeline_id() -> str:
    global _pipeline_id
    if _pipeline_id is None:
        existing = await pipelines.find_pipeline_by_label(settings.hubspot_pipeline_name)
        if existing is None:
            raise RuntimeError(
                f"HubSpot pipeline {settings.hubspot_pipeline_name!r} not found — "
                "run `python -m sales_agent.hubspot.bootstrap_pipeline` first"
            )
        _pipeline_id = existing["id"]
        for s in existing.get("stages", []):
            _stage_id_cache[s["label"]] = s["id"]
    return _pipeline_id


async def _resolve_stage_id(label: str) -> str | None:
    if label in _stage_id_cache:
        return _stage_id_cache[label]
    pid = await _resolve_pipeline_id()
    sid = await pipelines.stage_id_by_label(pid, label)
    if sid:
        _stage_id_cache[label] = sid
    return sid


def _enabled() -> bool:
    if not settings.hubspot_sync_enabled:
        return False
    if not settings.hubspot_pat:
        logger.warning("hubspot.sync: HUBSPOT_SYNC_ENABLED=true but HUBSPOT_PAT empty — skipping")
        return False
    return True


# ─── Lead sync ───────────────────────────────────────────────────────────────


async def sync_lead(repo: LeadRepo, lead: Lead) -> Lead:
    """Upsert Contact / Company / Deal for a lead and persist HubSpot ids back.

    Idempotent: if the lead already has hubspot ids, we update those records
    rather than creating duplicates.

    Returns the updated Lead row (with hubspot ids set). Returns the input
    lead unchanged if sync is disabled or HubSpot calls fail.
    """
    if not _enabled():
        return lead

    try:
        pipeline_id = await _resolve_pipeline_id()
        stage_label = STATUS_TO_STAGE_LABEL.get(lead.status)
        stage_id = await _resolve_stage_id(stage_label) if stage_label else None
        if stage_id is None and stage_label is not None:
            logger.warning(
                "hubspot.sync: stage %r not found in pipeline; skipping deal stage update",
                stage_label,
            )

        contact_id = await _upsert_contact(lead)
        company_id = await _upsert_company(lead)
        deal_id = await _upsert_deal(lead, pipeline_id, stage_id) if stage_id else lead.hubspot_deal_id

        if contact_id and company_id:
            await _associate(
                "contacts", contact_id, "companies", company_id, "contact_to_company",
            )
        if deal_id and contact_id:
            await _associate("deals", deal_id, "contacts", contact_id, "deal_to_contact")
        if deal_id and company_id:
            await _associate("deals", deal_id, "companies", company_id, "deal_to_company")

        return await repo.set_hubspot_ids(
            lead.id,
            contact_id=contact_id,
            company_id=company_id,
            deal_id=deal_id,
            synced_at=datetime.now(UTC),
        )
    except Exception:
        # Log and swallow — Postgres is canonical. Sync will retry on the next
        # state transition for this lead.
        logger.exception("hubspot.sync: sync_lead failed for lead=%s", lead.id)
        return lead


async def _upsert_contact(lead: Lead) -> str | None:
    if not lead.contact_email:
        return lead.hubspot_contact_id
    props = mapper.lead_to_contact_props(lead)

    if lead.hubspot_contact_id:
        await client.request(
            "PATCH", f"/crm/v3/objects/contacts/{lead.hubspot_contact_id}",
            json={"properties": props},
        )
        return lead.hubspot_contact_id

    # Try create; on 409 (already exists by email), look it up.
    try:
        body = await client.request(
            "POST", "/crm/v3/objects/contacts",
            json={"properties": props},
        )
        return body["id"]
    except client.HubSpotError as e:
        if e.status_code == 409:
            return await _find_contact_by_email(lead.contact_email)
        raise


async def _find_contact_by_email(email: str) -> str | None:
    body = await client.request(
        "POST", "/crm/v3/objects/contacts/search",
        json={
            "filterGroups": [{
                "filters": [{
                    "propertyName": "email",
                    "operator": "EQ",
                    "value": email.lower(),
                }],
            }],
            "limit": 1,
        },
    )
    results = body.get("results", [])
    return results[0]["id"] if results else None


async def _upsert_company(lead: Lead) -> str | None:
    props = mapper.lead_to_company_props(lead)
    if lead.hubspot_company_id:
        await client.request(
            "PATCH", f"/crm/v3/objects/companies/{lead.hubspot_company_id}",
            json={"properties": props},
        )
        return lead.hubspot_company_id

    body = await client.request(
        "POST", "/crm/v3/objects/companies",
        json={"properties": props},
    )
    return body["id"]


async def _upsert_deal(lead: Lead, pipeline_id: str, stage_id: str) -> str:
    props = mapper.lead_to_deal_props(lead, pipeline_id=pipeline_id, stage_id=stage_id)
    if lead.hubspot_deal_id:
        await client.request(
            "PATCH", f"/crm/v3/objects/deals/{lead.hubspot_deal_id}",
            json={"properties": props},
        )
        return lead.hubspot_deal_id

    body = await client.request(
        "POST", "/crm/v3/objects/deals",
        json={"properties": props},
    )
    return body["id"]


async def _associate(
    from_obj: str, from_id: str,
    to_obj: str, to_id: str,
    assoc_type: str,
) -> None:
    """Link two HubSpot objects. Idempotent — re-linking an existing pair is a no-op."""
    try:
        await client.request(
            "PUT",
            f"/crm/v3/objects/{from_obj}/{from_id}/associations/"
            f"{to_obj}/{to_id}/{assoc_type}",
        )
    except client.HubSpotError as e:
        # 4xx on already-associated is fine; surface the rest.
        if e.status_code not in (400, 409):
            raise


# ─── Send + reply sync ───────────────────────────────────────────────────────


async def sync_send(send_repo: SendRepo, lead: Lead, send: EmailSend) -> None:
    """Log an outbound email engagement on the lead's deal + contact."""
    if not _enabled():
        return

    try:
        props = mapper.send_to_email_engagement_props(send, direction="EMAIL")
        engagement_id = await _create_email_engagement(props, lead)
        if engagement_id:
            await send_repo.set_hubspot_engagement(send.id, engagement_id)

        stage_id = await _resolve_stage_id("Sent")
        if stage_id and lead.hubspot_deal_id:
            await client.request(
                "PATCH", f"/crm/v3/objects/deals/{lead.hubspot_deal_id}",
                json={"properties": {"dealstage": stage_id}},
            )
    except Exception:
        logger.exception("hubspot.sync: sync_send failed for send=%s", send.id)


async def sync_reply(send_repo: SendRepo, lead: Lead, send: EmailSend) -> None:
    """Log an inbound reply engagement and advance the deal stage to Replied."""
    if not _enabled():
        return

    try:
        props = mapper.send_to_email_engagement_props(send, direction="INCOMING_EMAIL")
        await _create_email_engagement(props, lead)

        stage_id = await _resolve_stage_id("Replied")
        if stage_id and lead.hubspot_deal_id:
            await client.request(
                "PATCH", f"/crm/v3/objects/deals/{lead.hubspot_deal_id}",
                json={"properties": {"dealstage": stage_id}},
            )
    except Exception:
        logger.exception("hubspot.sync: sync_reply failed for send=%s", send.id)


async def _create_email_engagement(
    props: dict[str, object], lead: Lead,
) -> str | None:
    body = await client.request(
        "POST", "/crm/v3/objects/emails",
        json={"properties": props},
    )
    engagement_id = body.get("id")
    if not engagement_id:
        return None

    # Associate to deal + contact if we have them.
    if lead.hubspot_deal_id:
        await _associate(
            "emails", engagement_id, "deals", lead.hubspot_deal_id, "email_to_deal",
        )
    if lead.hubspot_contact_id:
        await _associate(
            "emails", engagement_id, "contacts", lead.hubspot_contact_id, "email_to_contact",
        )
    return engagement_id
