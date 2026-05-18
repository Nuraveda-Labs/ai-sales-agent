"""Gmail Send via service-account domain-wide delegation.

The recipient sees a real Gmail send (Received: by mail-…google.com
headers) instead of "via resend.com / via amazonses.com" routing —
which is the strongest possible signal to Gmail's classifier that the
message is human, not bulk. Replies thread naturally to the operator's
Sent folder.

Auth chain (keyless — no SA JSON file on disk):
  Compute SA (default ADC on this box)
    → has roles/iam.serviceAccountTokenCreator on glitch-vertex-ai SA
      → glitch-vertex-ai SA has Workspace domain-wide delegation
        granted with scope https://www.googleapis.com/auth/gmail.send
        → mints an access token with `subject="support@..."` so the
          send is performed AS that Workspace user.

google.auth.iam.Signer uses the IAM Credentials API to sign JWTs on
behalf of the target SA without needing its private key. The signed
JWT is exchanged at the OAuth token endpoint for a gmail.send access
token scoped to the subject user.

Public surface mirrors resend_sender:
    send_plain(draft, lead)         → SendResult (plain text)
    send_branded_html(draft, lead)  → SendResult (multipart text+html)
    self_test()                     → str (Gmail message id)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from google.auth import default as google_default
from google.auth import iam
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from sales_agent.config import settings
from sales_agent.db.models import EmailDraft, EmailSend, Lead
from sales_agent.mail.render import render_branded_html, render_cold_text
from sales_agent.mail.resend_sender import SendResult, _safe_tag

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


_credentials: service_account.Credentials | None = None


def _get_credentials() -> service_account.Credentials:
    """Mint impersonated credentials with subject= for domain-wide delegation.

    Cached for the process lifetime; refreshed automatically when the
    underlying access token expires.
    """
    global _credentials
    if _credentials is None:
        if not settings.gcp_target_sa:
            raise RuntimeError("GCP_TARGET_SA not set — can't build Gmail credentials")
        if not settings.gmail_subject_user:
            raise RuntimeError("GMAIL_SUBJECT_USER not set — no user to act as")

        # 1. Get default credentials from the box's metadata server.
        source_creds, _ = google_default()

        # 2. Build a Signer that signs JWTs as the target SA via the IAM
        #    Credentials API (this is what avoids needing a JSON key file).
        signer = iam.Signer(
            request=Request(),
            credentials=source_creds,
            service_account_email=settings.gcp_target_sa,
        )

        # 3. Wrap as service_account.Credentials with the delegated subject.
        #    OAuth2 token endpoint will validate the JWT signature via
        #    Google's published SA public keys (no shared secret needed).
        _credentials = service_account.Credentials(
            signer=signer,
            service_account_email=settings.gcp_target_sa,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=GMAIL_SCOPES,
            subject=settings.gmail_subject_user,
        )

    if not _credentials.valid:
        try:
            _credentials.refresh(Request())
        except Exception as e:
            raise RuntimeError(
                f"failed to mint Gmail send token (subject={settings.gmail_subject_user}): {e}"
            ) from e

    return _credentials


def _build_service():
    """Build the Gmail API service. googleapiclient is sync — wrap calls in
    asyncio.to_thread."""
    creds = _get_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _from_header() -> str:
    """`Display Name <user@domain>` or bare email."""
    if settings.resend_from_name:
        return formataddr((settings.resend_from_name, settings.gmail_subject_user))
    return settings.gmail_subject_user


# ─── Message construction ───────────────────────────────────────────────────


def _build_plain_message(
    *, to_addr: str, reply_to: str, subject: str, body_text: str,
) -> dict[str, str]:
    """Plain-text MIME → base64url for Gmail's `users.messages.send`."""
    msg = MIMEText(body_text, "plain", "utf-8")
    msg["From"] = _from_header()
    msg["To"] = to_addr
    if reply_to and reply_to != settings.gmail_subject_user:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}


def _build_multipart_message(
    *, to_addr: str, reply_to: str, subject: str,
    text_body: str, html_body: str,
) -> dict[str, str]:
    """multipart/alternative — HTML + plain-text fallback."""
    msg = MIMEMultipart("alternative")
    msg["From"] = _from_header()
    msg["To"] = to_addr
    if reply_to and reply_to != settings.gmail_subject_user:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}


# ─── Send paths ─────────────────────────────────────────────────────────────


def _send_sync(message: dict[str, str]) -> dict:
    """Synchronous Gmail send — caller wraps in asyncio.to_thread."""
    service = _build_service()
    try:
        return service.users().messages().send(userId="me", body=message).execute()
    except HttpError as e:
        raise RuntimeError(
            f"Gmail send failed ({e.resp.status}): "
            f"{e.error_details if hasattr(e, 'error_details') else e}"
        ) from e


async def send_plain(*, draft: EmailDraft, lead: Lead) -> SendResult:
    if not lead.contact_email:
        raise ValueError(f"lead {lead.id} has no contact_email")

    body_text = render_cold_text(draft, lead)
    payload = _build_plain_message(
        to_addr=lead.contact_email,
        reply_to=settings.resend_reply_to or settings.gmail_subject_user,
        subject=draft.subject,
        body_text=body_text,
    )

    result = await asyncio.to_thread(_send_sync, payload)
    msg_id = result["id"]
    thread_id = result.get("threadId", msg_id)

    # Tag-style breadcrumbs aren't a Gmail concept — log instead so we
    # have the same per-recipe visibility we got from Resend tags.
    logger.info(
        "gmail.send_plain  lead=%s recipe=%s gmail_id=%s thread=%s",
        lead.business_name, _safe_tag(draft.recipe_key),
        msg_id, thread_id,
    )

    return SendResult(
        message_id=msg_id,
        thread_id=thread_id,
        from_email=settings.gmail_subject_user,
        to_email=lead.contact_email,
        subject=draft.subject,
        body=body_text,
        is_html=False,
    )


async def send_branded_html(
    *, draft: EmailDraft, lead: Lead,
    preview_text: str | None = None,
) -> SendResult:
    if not lead.contact_email:
        raise ValueError(f"lead {lead.id} has no contact_email")

    text_body = render_cold_text(draft, lead)
    html_body = render_branded_html(draft, lead, preview_text=preview_text)

    payload = _build_multipart_message(
        to_addr=lead.contact_email,
        reply_to=settings.resend_reply_to or settings.gmail_subject_user,
        subject=draft.subject,
        text_body=text_body,
        html_body=html_body,
    )

    result = await asyncio.to_thread(_send_sync, payload)
    msg_id = result["id"]
    thread_id = result.get("threadId", msg_id)

    logger.info(
        "gmail.send_branded_html  lead=%s recipe=%s gmail_id=%s",
        lead.business_name, _safe_tag(draft.recipe_key), msg_id,
    )

    return SendResult(
        message_id=msg_id,
        thread_id=thread_id,
        from_email=settings.gmail_subject_user,
        to_email=lead.contact_email,
        subject=draft.subject,
        body=html_body,
        is_html=True,
    )


async def self_test() -> str:
    """Send a test from `subject_user` to `subject_user`. Returns Gmail
    message id on success; raises on auth / scope / API failure."""
    payload = _build_plain_message(
        to_addr=settings.gmail_subject_user,
        reply_to=settings.gmail_subject_user,
        subject="Glitch Budz sales agent — Gmail Send self-test",
        body_text=(
            "Programmatic self-test. If you read this, the Gmail Send wire "
            "via service-account domain-wide delegation is healthy.\n\n"
            "— sales agent self-test\n"
        ),
    )
    result = await asyncio.to_thread(_send_sync, payload)
    return result["id"]
