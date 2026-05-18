"""Outbound mail via Resend's REST API.

Why Resend over SMTP/Gmail-API:
- One API key, one POST per email. No OAuth refresh, no SMTP banner dance.
- Domain-verified sending — `example.com` already has DKIM + DMARC
  set up in Resend's dashboard; we send from any address on it.
- Built-in idempotency via the `Idempotency-Key` header — safe under
  retries.
- Returns a stable `id` we persist to `email_sends.gmail_message_id`
  (column name kept for backwards compatibility — the value is now a
  Resend message id, not a Gmail one).

What we send:
- **Cold email 1**: plain-text body via `render_cold_text`. No HTML, no
  tracking pixel — keeps deliverability + reply rate high.
- **Email 2 / follow-ups**: HTML via `render_branded_html` + plain-text
  fallback for accessibility-mode clients.

What's NOT here:
- Reply tracking. Replies land in the actual mailbox; an IMAP poller
  (separate sprint) reads them and updates `email_sends.replied_at`.
- Open tracking. Cold email 1 deliberately ships without the pixel
  because cold + image = spam-flag risk; we'll add it for email 2.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from sales_agent.config import settings
from sales_agent.db.models import EmailDraft, Lead
from sales_agent.mail.render import render_branded_html, render_cold_text

logger = logging.getLogger(__name__)

RESEND_BASE = "https://api.resend.com"


@dataclass
class SendResult:
    message_id: str
    thread_id: str       # we synthesize this from message_id for v1 — no native concept in Resend
    from_email: str
    to_email: str
    subject: str
    body: str            # exact text/html that went out
    is_html: bool


class ResendError(RuntimeError):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"Resend {status_code}: {body[:500]}")
        self.status_code = status_code
        self.body = body


_RETRYABLE = (httpx.TransportError, httpx.ReadTimeout, httpx.ConnectTimeout)


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        if not settings.resend_api_key:
            raise RuntimeError("RESEND_API_KEY not set in .env")
        _client = httpx.AsyncClient(
            base_url=RESEND_BASE,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _post(path: str, payload: dict, *, idempotency_key: str | None = None) -> dict:
    client = _get_client()
    headers = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    async for attempt in AsyncRetrying(
        wait=wait_exponential(multiplier=1, min=1, max=15),
        stop=stop_after_attempt(4),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    ):
        with attempt:
            resp = await client.post(path, json=payload, headers=headers)
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                raise httpx.TransportError(
                    f"Resend {resp.status_code}: {resp.text[:200]}"
                )
            if 400 <= resp.status_code < 500:
                raise ResendError(resp.status_code, resp.text)
            return resp.json()
    raise RuntimeError("unreachable")  # tenacity exhausted


def _from_header() -> str:
    """Resend accepts both `Name <email>` and bare `email`. Use the named form."""
    if settings.resend_from_name:
        return f"{settings.resend_from_name} <{settings.resend_from_email}>"
    return settings.resend_from_email


def _safe_tag(s: str) -> str:
    """Resend tag values: ASCII letters, numbers, underscores, dashes only.
    Coerce anything else to `-` so we can pass arbitrary platform / recipe
    keys without 422-ing the API."""
    import re

    return re.sub(r"[^A-Za-z0-9_-]", "-", s) or "unknown"


# ─── Public surface ──────────────────────────────────────────────────────────


async def send_plain(
    *, draft: EmailDraft, lead: Lead,
    idempotency_key: str | None = None,
) -> SendResult:
    """Send a plain-text cold email (email 1).

    Caller is responsible for ensuring the lead's `contact_email` is
    populated and not in `sales_agent.unsubscribes` (the workflow
    layer does both checks before this is called).
    """
    if not lead.contact_email:
        raise ValueError(f"lead {lead.id} has no contact_email")

    body_text = render_cold_text(draft, lead)
    payload = {
        "from":     _from_header(),
        "to":       [lead.contact_email],
        "reply_to": settings.resend_reply_to,
        "subject":  draft.subject,
        "text":     body_text,
        # Resend tags: ASCII letters, numbers, underscores, dashes only.
        # recipe_key carries platform:hook_name (e.g. "<vertical-tool-3>:switching_cost_safe")
        # so the colon needs to be sanitized for tag use; the DB still stores
        # the canonical colon form.
        "tags":     [
            {"name": "recipe", "value": _safe_tag(draft.recipe_key)},
            {"name": "platform", "value": _safe_tag(lead.pos_platform or "unknown")},
            {"name": "follow_up_seq", "value": "0"},
        ],
    }
    idem = idempotency_key or f"draft:{draft.id}"
    resp = await _post("/emails", payload, idempotency_key=idem)
    msg_id = resp["id"]
    logger.info(
        "resend.send_plain: lead=%s draft=%s → resend_id=%s",
        lead.business_name, draft.id, msg_id,
    )
    return SendResult(
        message_id=msg_id,
        thread_id=f"resend:{msg_id}",
        from_email=settings.resend_from_email,
        to_email=lead.contact_email,
        subject=draft.subject,
        body=body_text,
        is_html=False,
    )


async def send_branded_html(
    *, draft: EmailDraft, lead: Lead,
    preview_text: str | None = None,
    idempotency_key: str | None = None,
) -> SendResult:
    """Send the branded HTML email — email 2 / follow-ups / customer onboarding.

    Includes the plain-text body as the multipart fallback so accessibility-
    mode clients (and spam filters that prefer text-only) get a clean read.
    """
    if not lead.contact_email:
        raise ValueError(f"lead {lead.id} has no contact_email")

    text_body = render_cold_text(draft, lead)
    html_body = render_branded_html(draft, lead, preview_text=preview_text)

    payload = {
        "from":     _from_header(),
        "to":       [lead.contact_email],
        "reply_to": settings.resend_reply_to,
        "subject":  draft.subject,
        "text":     text_body,
        "html":     html_body,
        "tags":     [
            {"name": "recipe", "value": _safe_tag(draft.recipe_key)},
            {"name": "platform", "value": _safe_tag(lead.pos_platform or "unknown")},
            {"name": "format", "value": "branded_html"},
        ],
    }
    idem = idempotency_key or f"draft:{draft.id}:html"
    resp = await _post("/emails", payload, idempotency_key=idem)
    msg_id = resp["id"]
    logger.info(
        "resend.send_branded_html: lead=%s draft=%s → resend_id=%s",
        lead.business_name, draft.id, msg_id,
    )
    return SendResult(
        message_id=msg_id,
        thread_id=f"resend:{msg_id}",
        from_email=settings.resend_from_email,
        to_email=lead.contact_email,
        subject=draft.subject,
        body=html_body,
        is_html=True,
    )


async def self_test() -> str:
    """Send a test message from `from` to `from`. Returns the Resend
    message id on success; raises on auth / domain / API failure.
    Useful as a pre-flight before any real cold mail goes out."""
    payload = {
        "from":     _from_header(),
        "to":       [settings.resend_from_email],
        "reply_to": settings.resend_reply_to,
        "subject":  "Example Brand sales agent — self-test",
        "text":     (
            "If you're reading this, the sales agent's Resend wire is healthy.\n\n"
            "— sales agent self-test (programmatic)\n"
        ),
    }
    idem = f"selftest:{uuid.uuid4()}"
    resp = await _post("/emails", payload, idempotency_key=idem)
    return resp["id"]
