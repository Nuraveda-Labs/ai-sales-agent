"""Render outbound email bodies — both plain-text and HTML.

For cold email 1 we always send plain text (deliverability + reply-rate
reasons). For email 2 / replies / customer onboarding we use the
branded HTML template in `templates/cold_email.html`.

Plain-text always carries the CASL footer. HTML carries the same plus
a styled signature block.

The sender module (next sprint) calls one of:
    render_cold_text(draft, lead) → str
    render_branded_html(draft, lead, *, preview_text) → str

Both return a fully ready-to-send body. No further substitution needed.
"""

from __future__ import annotations

import html
from pathlib import Path
from string import Template

from sales_agent.config import settings
from sales_agent.db.models import EmailDraft, Lead

DEMO_URL = "https://exotic420budz.com"
LANDING_URL = "https://grow.example.com/budz"
# Full name on the sign-off — the body voice is casual lowercase but the
# signature is a real name (Title Case proper noun) so the recipient
# knows who's emailing them.
SENDER_NAME = "Tejas Karan Agrawal"


def _booking_url() -> str:
    """Live booking URL from settings, with a sane fallback to the landing
    page when no calendar link is configured (so the CTA still works in dev)."""
    return settings.booking_url or LANDING_URL

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "cold_email.html"


# ─── Plain-text ──────────────────────────────────────────────────────────────


def render_cold_text(draft: EmailDraft, lead: Lead) -> str:
    """Plain-text body with sign-off + CASL footer.

    The recipe body now carries the URL block inline (in the prose's
    natural flow), so we no longer append "live demo: ...\\n book here:
    ..." after the body — that would duplicate. Render just appends
    the personal sign-off + the legally-required CASL identification
    + unsubscribe note.
    """
    return (
        f"{draft.body.rstrip()}\n"
        f"\n"
        f"— {SENDER_NAME}\n"
        f"\n"
        f"---\n"
        f"{settings.casl_sender_name} · {settings.casl_sender_address}\n"
        f"reply 'stop' to unsubscribe\n"
    )


# ─── Branded HTML ────────────────────────────────────────────────────────────


def _body_to_html_paragraphs(body: str) -> str:
    """Convert the recipe body's plain text into branded HTML paragraphs.

    - Blank line → paragraph break.
    - **bold** stays bold (recipe templates use it for the price hook).
    - URLs become anchor tags styled with the electric-blue accent.
    - Bullet lines (`- foo`) become a `<ul>` block.
    """
    paragraphs: list[str] = []
    buffer: list[str] = []
    in_list = False

    def flush_buffer() -> None:
        if buffer:
            text = "<br/>".join(html.escape(line) for line in buffer)
            text = _bold_to_html(text)
            text = _link_to_html(text)
            paragraphs.append(f'<p style="margin:0 0 12px 0;">{text}</p>')
            buffer.clear()

    def flush_list(items: list[str]) -> None:
        if items:
            li = "".join(
                f'<li style="margin:0 0 4px 0;">{_link_to_html(_bold_to_html(html.escape(it)))}</li>'
                for it in items
            )
            paragraphs.append(
                f'<ul style="margin:0 0 12px 0;padding-left:20px;color:#1f2937;">{li}</ul>'
            )

    list_items: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if in_list:
                flush_list(list_items)
                list_items = []
                in_list = False
            else:
                flush_buffer()
            continue
        if stripped.startswith("- "):
            flush_buffer()
            in_list = True
            list_items.append(stripped[2:])
            continue
        if in_list:
            flush_list(list_items)
            list_items = []
            in_list = False
        buffer.append(stripped)

    flush_list(list_items)
    flush_buffer()

    return "\n".join(paragraphs) or '<p style="margin:0;"></p>'


def _bold_to_html(text: str) -> str:
    """Convert **markdown** bold to <strong> while preserving HTML escaping."""
    out: list[str] = []
    parts = text.split("**")
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(f'<strong style="color:#0a0a0f;">{part}</strong>')
        else:
            out.append(part)
    return "".join(out)


def _link_to_html(text: str) -> str:
    """Turn bare URLs (already-escaped) into branded anchor tags."""
    import re

    def replace(m: "re.Match[str]") -> str:
        url = m.group(0)
        return (
            f'<a href="{url}" style="color:#0088ff;text-decoration:none;'
            f'border-bottom:1px solid #cbd5e1;">{url}</a>'
        )

    return re.sub(r"https?://[^\s<>\"]+|exotic420budz\.com", replace, text)


def render_branded_html(
    draft: EmailDraft,
    lead: Lead,
    *,
    preview_text: str | None = None,
    tracking_pixel_url: str | None = None,
) -> str:
    """Render the branded HTML email for follow-ups / customer onboarding.

    NOT used for cold email 1 — that goes plain text via render_cold_text.
    """
    template = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    body_html = _body_to_html_paragraphs(draft.body)

    pixel = (
        f'<img src="{tracking_pixel_url}" width="1" height="1" '
        f'alt="" style="display:block;width:1px;height:1px;" />'
        if tracking_pixel_url
        else ""
    )
    preview = preview_text or (
        f"$999 setup, $99/mo flat — {lead.business_name} on a real cannabis storefront."
    )

    unsubscribe_url = f"mailto:{settings.gmail_sender_email}?subject=stop"

    return template.safe_substitute(
        subject=html.escape(draft.subject),
        opener=html.escape(draft.body.split("\n", 1)[0]),
        body_html=body_html,
        sender_name=SENDER_NAME,
        demo_url=DEMO_URL,
        landing_url=LANDING_URL,
        booking_url=_booking_url(),
        booking_duration=str(settings.booking_duration_min),
        casl_entity=html.escape(settings.casl_sender_name),
        casl_address=html.escape(settings.casl_sender_address),
        unsubscribe_url=unsubscribe_url,
        preview_text=html.escape(preview),
        tracking_pixel=pixel,
    )
