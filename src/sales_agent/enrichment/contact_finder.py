"""Resolve a contact email for a lead.

Strategy, in order:
1. Fetch homepage + a small set of likely contact pages, scrape `mailto:`
   anchors and email-shaped strings. If multiple are found, prefer one
   on the same domain as the website.
2. If nothing found, fall back to a pattern-guess (`info@<domain>`) but
   ONLY when the lead is on its own domain (not a Wix/Linktree subdomain).
   Verify the domain has MX records before returning the guess.
3. Otherwise return `(None, None)` and let downstream skip this lead.

We don't SMTP-probe the local part — most servers reject RCPT TO
verifications and it's a spam signal. Better to send to `info@` and let
a bounce or no-reply tell us the address is wrong.
"""

from __future__ import annotations

import logging
import re
from typing import Literal
from urllib.parse import urljoin, urlparse

import dns.asyncresolver
import dns.exception
import httpx
from selectolax.parser import HTMLParser

from sales_agent.enrichment.site_detector import LINKTREE_HOSTS, SiteStatus

logger = logging.getLogger(__name__)

# Which source produced the address — written to leads.contact_email_source.
EmailSource = Literal["footer", "ig_bio", "pattern_guess", "reply"]

# Lenient email regex; tightened by the blacklist below.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}"
)

# Domains we always reject — SaaS hosts, CDN/analytics providers, common
# false positives baked into builder templates. Each entry matches if the
# email's domain equals it OR ends with `.<entry>`.
_BLACKLIST_DOMAINS: frozenset[str] = frozenset({
    "wix.com", "wixsite.com", "squarespace.com", "weebly.com",
    "godaddy.com", "godaddysites.com", "carrd.co", "wordpress.com",
    "shopify.com", "myshopify.com",
    "googleapis.com", "google.com", "gstatic.com",
    "cloudflare.com", "cloudfront.net",
    "sentry.io", "intercom.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "example.com", "domain.com", "yourdomain.com", "test.com",
    "sample.com",
})

# Asset-file extensions that look like TLDs to a permissive email regex —
# things like `ajax-loader@2x.gif` or `group-20@2x.jpg` come from
# sprite-sheet filenames in builder templates and are NOT email addresses.
_ASSET_EXTENSIONS: frozenset[str] = frozenset({
    "gif", "png", "jpg", "jpeg", "svg", "webp", "ico", "bmp",
    "css", "js", "json", "map", "xml",
    "woff", "woff2", "ttf", "otf", "eot",
    "mp4", "mp3", "webm", "avi", "mov",
    "pdf", "zip",
})

_PATHS_TO_TRY: tuple[str, ...] = (
    "/", "/contact", "/contact-us", "/about", "/about-us",
    "/get-in-touch", "/connect", "/info",
)


def _domain_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url if "://" in url else f"https://{url}").hostname
    except (ValueError, TypeError):
        return None
    if not host:
        return None
    return host.lower().removeprefix("www.")


def _is_blacklisted(email: str) -> bool:
    domain = email.split("@", 1)[-1].lower()
    # Asset-file TLDs (gif, png, css, woff2, …) — sprite-sheet filenames
    # like `ajax-loader@2x.gif` get caught here.
    last_dot = domain.rfind(".")
    if last_dot >= 0 and domain[last_dot + 1:] in _ASSET_EXTENSIONS:
        return True
    for bad in _BLACKLIST_DOMAINS:
        if domain == bad or domain.endswith("." + bad):
            return True
    return False


def _is_aggregator_host(domain: str) -> bool:
    for h in LINKTREE_HOSTS:
        if domain == h or domain.endswith("." + h):
            return True
    # Hosted-builder subdomains (info@<shop>.wixsite.com is meaningless)
    for bad in ("wixsite.com", "weebly.com", "godaddysites.com", "myshopify.com",
                "carrd.co", "wordpress.com"):
        if domain.endswith("." + bad):
            return True
    return False


async def _scrape_emails_one_page(
    url: str, client: httpx.AsyncClient,
) -> list[str]:
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15.0)
    except (httpx.TransportError, httpx.TimeoutException):
        return []
    if resp.status_code >= 400 or not resp.text:
        return []

    found: set[str] = set()
    parser = HTMLParser(resp.text)

    # mailto: anchors are the highest-signal source.
    for a in parser.css("a[href^='mailto:']"):
        href = (a.attributes or {}).get("href", "") or ""
        addr = href.removeprefix("mailto:").split("?")[0].strip()
        if "@" in addr and not _is_blacklisted(addr):
            found.add(addr.lower())

    # Plain regex over the rendered text + raw HTML — catches obfuscated
    # `info [at] domain [dot] com` is out of scope, but plain emails in
    # footers + JSON-LD blocks are caught here.
    for m in _EMAIL_RE.finditer(resp.text):
        addr = m.group(0).lower()
        if not _is_blacklisted(addr):
            found.add(addr)

    return list(found)


async def _has_mx(domain: str) -> bool:
    try:
        resolver = dns.asyncresolver.Resolver()
        resolver.lifetime = 5.0
        result = await resolver.resolve(domain, "MX")
        return any(True for _ in result)
    except (dns.exception.DNSException, OSError):
        return False


async def find_contact_email(
    website_url: str | None,
    site_status: SiteStatus,
    client: httpx.AsyncClient,
) -> tuple[str | None, EmailSource | None]:
    """Multi-strategy email resolution. Returns (email, source) or (None, None)."""
    if not website_url:
        return None, None

    # Build the candidate URL set. Each path is joined against the website's
    # origin, not blindly appended, so it works whether website_url has a
    # trailing slash or not.
    parsed = urlparse(website_url if "://" in website_url else f"https://{website_url}")
    base = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [urljoin(base + "/", p.lstrip("/")) for p in _PATHS_TO_TRY]

    found: list[str] = []
    for url in candidates:
        emails = await _scrape_emails_one_page(url, client)
        if emails:
            found.extend(emails)
            if len(found) >= 5:
                break

    if found:
        domain = _domain_of(website_url)
        if domain:
            same_domain = [e for e in found if e.split("@", 1)[-1] == domain]
            if same_domain:
                return same_domain[0], "footer"
        return found[0], "footer"

    # Fallback: pattern guess. Only meaningful for shops on their own
    # domain. Skip aggregator hosts, builder subdomains, and "none" sites.
    if site_status not in ("custom", "lightspeed"):
        return None, None
    domain = _domain_of(website_url)
    if not domain or _is_aggregator_host(domain):
        return None, None
    if not await _has_mx(domain):
        return None, None
    return f"info@{domain}", "pattern_guess"
