"""Detect a shop's POS / e-commerce platform from its website.

Classifies into a `PosPlatform` enum that the recipe library keys on.
The categories were derived empirically from the 77-lead Toronto cohort
probe (see `migrations/0003_pos_platform.sql` header for definitions).

Detection priority (highest signal first):
    tendypos > dutchie > blaze > shopify > brochure > custom > none

We follow shop subdomains (`shop.*`, `order.*`, `store.*`, `menu.*`)
because for cannabis retail the apex domain is often a Squarespace/WP
brochure while the actual e-commerce backend lives on a subdomain
hosted by Dutchie / Blaze / TendyPOS. Skipping the subdomain hides
the platform that actually matters for the pitch.
"""

from __future__ import annotations

import logging
import re
from typing import Literal
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

PosPlatform = Literal[
    "none", "brochure", "dutchie", "blaze", "tendypos", "shopify", "custom",
]


# Pattern, in priority order. First match wins.
_POS_PATTERNS: tuple[tuple[PosPlatform, re.Pattern[str]], ...] = (
    ("tendypos", re.compile(
        r"tendy[a-z]*\.api\.unoapp\.io|tendypos\.com|tendy-budler", re.I,
    )),
    ("dutchie", re.compile(
        r"dutchie\.com|embed\.dutchie|dutchie\.menu|cdn\.dutchie", re.I,
    )),
    ("blaze", re.compile(
        r"blaze\.me|blazenow|blaze-now|cdn\.blaze[a-z]*\.io", re.I,
    )),
    ("shopify", re.compile(
        r"cdn\.shopify\.com|myshopify\.com|/cdn/shop/", re.I,
    )),
)

# Brochure-only signatures (Squarespace, Wix, WordPress) when no shop
# subdomain or POS signature was detected on the apex.
_BROCHURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"squarespace-cdn\.com|static1\.squarespace", re.I),
    re.compile(r"wixstatic\.com|wix\.com/website|_wix_", re.I),
    re.compile(r"wp-content/|wp-includes/|wordpress\.com", re.I),
)

# Shop-subdomain hint in apex links — if the apex points at a `shop.*`,
# fetch that and probe for POS signatures there too.
_SHOP_LINK_RE = re.compile(
    r'https?://(?:shop|order|store|menu)\.[a-z0-9.\-]+(?:/[a-z0-9.\-/_?=&%]*)?',
    re.I,
)

# Blaze fallback: known Blaze shop URLs follow `/menu/<location>/` path
# even when the bare `blaze.me` substring isn't in the HTML.
_BLAZE_PATH_HINT = re.compile(
    r'https?://shop\.[a-z0-9.\-]+/menu/[a-z0-9.\-/_]+', re.I,
)


def _host(url: str) -> str | None:
    try:
        host = urlparse(url if "://" in url else f"https://{url}").hostname
    except (ValueError, TypeError):
        return None
    return host.lower().removeprefix("www.") if host else None


async def _fetch(client: httpx.AsyncClient, url: str, *, timeout: float = 12.0) -> str:
    try:
        r = await client.get(url, follow_redirects=True, timeout=timeout)
    except (httpx.TransportError, httpx.TimeoutException) as e:
        logger.debug("fetch failed for %s: %s", url, e)
        return ""
    if r.status_code >= 400:
        return ""
    return r.text or ""


def _classify(html_combined: str, shop_url: str | None) -> PosPlatform | None:
    """Pure classifier: takes already-fetched HTML, returns a PosPlatform or None."""
    if not html_combined:
        return None
    for tag, rx in _POS_PATTERNS:
        if rx.search(html_combined):
            return tag
    # Blaze fallback by URL shape, when patterns missed.
    if shop_url and _BLAZE_PATH_HINT.search(shop_url):
        return "blaze"
    return None


async def detect_pos_platform(
    url: str | None, client: httpx.AsyncClient,
) -> PosPlatform:
    """Top-level: fetch apex + (optional) shop subdomain, classify.

    Returns "none" when the site is unreachable / blank, "brochure" when
    a CMS signature is present without a real shop, "custom" when nothing
    matches but the page exists, otherwise the matching POS platform.
    """
    if not url:
        return "none"
    apex = await _fetch(client, url)
    if not apex or len(apex) < 200:
        return "none"

    # Find a linked shop subdomain in the apex; if so, fetch it too.
    shop_url: str | None = None
    m = _SHOP_LINK_RE.search(apex)
    if m:
        shop_url = m.group(0)

    sub = await _fetch(client, shop_url) if shop_url else ""
    combined = apex + "\n" + sub

    pos = _classify(combined, shop_url)
    if pos:
        return pos

    # No POS signature. Decide between brochure / custom.
    for rx in _BROCHURE_PATTERNS:
        if rx.search(apex):
            return "brochure"
    return "custom"


# ─── Backwards-compatible legacy API ────────────────────────────────────────
# `current_site_status` (none/linktree/builder/lightspeed/custom) is still
# referenced by the old run_enrichment path. Map the new enum to the old
# one so that column stays consistent for any downstream readers.

LegacySiteStatus = Literal["none", "linktree", "builder", "lightspeed", "custom"]

# Re-exported for the rest of the package to keep imports consistent.
SiteStatus = LegacySiteStatus  # legacy alias

# Hosts considered link aggregators — used by the contact_finder for
# "don't pattern-guess at info@<host>" decisions; kept here for one
# import site.
LINKTREE_HOSTS: frozenset[str] = frozenset({
    "linktr.ee", "lnk.bio", "beacons.ai", "bio.link", "snipfeed.co",
    "linkin.bio", "stan.store", "withkoji.com", "campsite.bio",
})


def pos_to_legacy(pos: PosPlatform) -> LegacySiteStatus:
    """Best-effort mapping for filling the legacy column."""
    if pos == "none":
        return "none"
    if pos == "brochure":
        return "builder"          # closest legacy bucket
    if pos in ("dutchie", "blaze", "tendypos", "shopify"):
        return "custom"           # they have a real ecom backend
    return "custom"


async def detect(
    url: str | None, client: httpx.AsyncClient, *, timeout: float = 12.0,
) -> LegacySiteStatus:
    """Legacy entry point used by the v1 run_enrichment path. Returns the
    LEGACY enum value derived from the new pos_platform classification."""
    pos = await detect_pos_platform(url, client)
    return pos_to_legacy(pos)
