"""Pure functions: Postgres row → HubSpot v3 property dict.

No I/O, no settings reads, no logging. Each function is a pure transform
so they're trivial to unit-test and the sync layer can decide what to do
with the resulting payload (create vs update, with-association vs without).
"""

from __future__ import annotations

from urllib.parse import urlparse

from sales_agent.db.models import EmailSend, Lead


def _domain_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url if "://" in url else f"https://{url}").hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def lead_to_contact_props(lead: Lead) -> dict[str, str]:
    """Build the HubSpot Contact properties payload from a lead.

    HubSpot's contact dedup key is `email` (lower-cased internally). We pass
    the business name as `lastname` because we don't reliably know an
    operator's first/last name during cold discovery — `lastname` is
    HubSpot's required-ish field and using the business name there keeps
    the contact recognizable in the UI's contact list.
    """
    return {
        "email": (lead.contact_email or "").lower(),
        "firstname": "",
        "lastname": lead.business_name,
        "company": lead.business_name,
        "phone": lead.phone or "",
        "website": lead.website_url or "",
        "city": lead.city or "",
        "state": lead.province,
        "zip": lead.postal_code or "",
        # Custom contact properties — must exist in the portal. Created by
        # `pipelines.ensure_custom_properties()` on first bootstrap.
        "current_site_status": lead.current_site_status or "",
        "agent_score": str(lead.score),
    }


def lead_to_company_props(lead: Lead) -> dict[str, str]:
    """Build the HubSpot Company properties payload from a lead.

    HubSpot's company dedup key is `domain`. If the lead has no website,
    HubSpot creates a domainless company keyed on `name` — fine for v1.
    """
    return {
        "name": lead.business_name,
        "domain": _domain_of(lead.website_url),
        "phone": lead.phone or "",
        "address": lead.address or "",
        "city": lead.city or "",
        "state": lead.province,
        "zip": lead.postal_code or "",
        # Custom company property — must exist. See ensure_custom_properties.
        "agco_license": lead.agco_license or "",
    }


def lead_to_deal_props(
    lead: Lead, *, pipeline_id: str, stage_id: str,
) -> dict[str, str]:
    """Build the HubSpot Deal properties payload."""
    return {
        "dealname": f"Glitch Budz · {lead.business_name}",
        "pipeline": pipeline_id,
        "dealstage": stage_id,
    }


def send_to_email_engagement_props(
    send: EmailSend, *, direction: str = "EMAIL",
) -> dict[str, object]:
    """Build the HubSpot Email engagement payload.

    `direction` is "EMAIL" for outbound, "INCOMING_EMAIL" for replies.
    HubSpot expects the timestamp in milliseconds since epoch.

    HubSpot deprecated separate `hs_email_from_email` / `hs_email_to_email`
    fields — they now derive those from the structured `hs_email_headers`
    JSON property. Build that JSON shape instead so the API doesn't 400.
    """
    import json

    timestamp_ms = int(send.sent_at.timestamp() * 1000)
    headers = {
        "from": {"email": send.from_email, "firstName": "", "lastName": ""},
        "to": [{"email": send.to_email, "firstName": "", "lastName": ""}],
        "cc": [],
        "bcc": [],
    }
    return {
        "hs_timestamp":      timestamp_ms,
        "hs_email_direction": direction,
        "hs_email_subject":  send.subject,
        "hs_email_text":     send.body,
        "hs_email_headers":  json.dumps(headers),
        "hs_email_status":    "SENT",
    }
