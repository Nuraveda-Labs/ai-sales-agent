"""Founder-personal one-off send.

Sends a plain founder DM (not via cold-outreach renderer) using the
sales-agent's Gmail SA + DWD auth chain. Used to honour the 24-hour
welcome-email promise to free Vibe Kit leads.

Usage:
    cd /home/support/ai_marketing_stack-sales-agent-private
    source .venv/bin/activate
    PYTHONPATH=src python3 scripts/send_founder_dm.py \\
        --to guravsuyog123@gmail.com \\
        --to-name "Suyog" \\
        --subject "Suyog — the Glitch Vibe Kit (1 download, then we'll talk)" \\
        --body-file /home/support/ai_marketing_stack-sales-agent-private/scripts/_outbox/suyog.md

The body-file is markdown; we send it as plain text + a minimal HTML
multipart so the recipient renders cleanly in any client.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import sys
from pathlib import Path

from sales_agent.mail import gmail_sender


def md_to_html(md: str) -> str:
    """Tiny markdown → HTML for one-off founder DMs. No external dep.

    Handles: bold (**x**), inline `code`, [text](url), blank-line
    paragraphs, basic `- ` bullets. Anything else stays raw.
    """
    paras = [p.strip() for p in md.split("\n\n") if p.strip()]
    out: list[str] = []
    for p in paras:
        # Bullet list?
        if p.startswith("- "):
            items = [line[2:].strip() for line in p.split("\n") if line.startswith("- ")]
            inner = "\n".join(
                f"<li style=\"margin:0 0 6px;\">{_inline(line)}</li>" for line in items
            )
            out.append(f"<ul style=\"margin:0 0 16px;padding-left:20px;\">{inner}</ul>")
        else:
            out.append(f"<p style=\"margin:0 0 16px;font-size:15px;line-height:1.6;\">{_inline(p)}</p>")
    body = "\n".join(out)
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1a1a1a;background:#ffffff;">
<div style="max-width:560px;margin:0 auto;">{body}</div>
</body></html>"""


def _inline(s: str) -> str:
    import re
    # escape first, then re-apply markdown patterns
    s = html.escape(s)
    # **bold**
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    # `code`
    s = re.sub(r"`([^`]+)`", r"<code style=\"background:#f1f1f1;padding:1px 5px;border-radius:3px;font-family:Menlo,monospace;font-size:13px;\">\1</code>", s)
    # [text](url)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" style="color:#0a66c2;text-decoration:underline;">\1</a>', s)
    # convert single newlines inside a paragraph to <br>
    s = s.replace("\n", "<br>")
    return s


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="Recipient email")
    ap.add_argument("--to-name", default="", help="Recipient first name (for greeting)")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body-file", required=True, help="Path to markdown body")
    ap.add_argument("--reply-to", default="support@example.com")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    body_md = Path(args.body_file).read_text(encoding="utf-8")
    text_body = body_md  # plain-text leg is the raw markdown — readable as-is
    html_body = md_to_html(body_md)

    if args.dry_run:
        print(f"DRY RUN — would send to {args.to}")
        print(f"Subject: {args.subject}")
        print(f"--- text leg ({len(text_body)} chars) ---")
        print(text_body[:500])
        print("...")
        print(f"--- html leg ({len(html_body)} chars) ---")
        return

    payload = gmail_sender._build_multipart_message(
        to_addr=args.to,
        reply_to=args.reply_to,
        subject=args.subject,
        text_body=text_body,
        html_body=html_body,
    )
    result = await asyncio.to_thread(gmail_sender._send_sync, payload)
    print(f"✓ sent to {args.to}")
    print(f"  Gmail message id: {result.get('id')}")
    print(f"  Thread id:        {result.get('threadId')}")
    print(f"  Label IDs:        {result.get('labelIds')}")


if __name__ == "__main__":
    asyncio.run(main())
