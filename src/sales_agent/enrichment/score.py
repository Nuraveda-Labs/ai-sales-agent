"""Lead scoring heuristic.

Computes an integer 0–100 priority score per enriched lead. Higher means
"send first." The drafter and HITL surface order leads by this column,
so getting the heuristic roughly right early matters more than getting
it perfectly right.

Scoring mental model:
- Independents > chains. Chains have corporate procurement and won't
  switch on a $99/mo pitch.
- Reachability matters. No email = no send = no value, regardless of
  fit.
- Site weakness signals fit. Linktree / no-site / Wix shops feel the
  pain we're solving more than custom-built shops.
"""

from __future__ import annotations

import logging
from collections import Counter
from urllib.parse import urlparse

from sales_agent.db.models import Lead

logger = logging.getLogger(__name__)


# Substrings that flag a lead as a corporate/multi-location chain. Match
# is case-insensitive against business_name. Maintained by hand from
# observation of the cohort — add as new chains surface.
CHAIN_KEYWORDS: tuple[str, ...] = (
    "canna cabana", "high tide",                # Canna Cabana / High Tide Inc.
    "spiritleaf",
    "fire & flower", "fire and flower", "fireandflower",
    "one plant",
    "sessions cannabis",
    "hunny pot",
    "friendly stranger",
    "fika cannabis",
    "ashario",
    "pop's cannabis",
    "matchbox cannabis",
    "value buds",
    "nova cannabis",
    "tokyo smoke",
    "fogtown",
    "hexo",
    "sundial",
    "stash & co",
    "north of 49",
    "weedjar",
    "moksha cannabis",                          # 3+ locations in cohort
    "fika",
    "purple moose",
    "maryjane",                                 # MaryJane's Weed Dispensary
)

# Platform fit bonus. After the Apr-2026 product reframe, the pitch is
# "we add a premium storefront on top of what you have, with AI SEO."
# Brochure / no-site shops get the standalone pitch (most acute pain).
# Dutchie / Blaze / TendyPOS shops get the additive-layer pitch (real
# but slower-burn — they have something working).
# Shopify shops are almost always chains; bench them out of the queue.
_PLATFORM_BONUS: dict[str, int] = {
    "none":      25,   # no site at all → easiest "we'll get you online" pitch
    "brochure":  25,   # Squarespace/Wix/WP without real ordering
    "dutchie":   20,   # working stack, AI SEO upgrade pitch lands
    "blaze":     20,   # same shape as Dutchie
    "tendypos":  20,   # same shape
    "shopify":  -50,   # chains; wrong ICP
    "custom":     0,
}

# Legacy alias retained for backwards compatibility — points at the
# new bonus map until the old current_site_status field is fully
# decommissioned.
_SITE_BONUS = _PLATFORM_BONUS


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


def _matches_chain(business_name: str) -> bool:
    name = business_name.lower()
    return any(kw in name for kw in CHAIN_KEYWORDS)


def domain_counts(leads: list[Lead]) -> Counter[str]:
    """Count leads per (canonical) website domain across the cohort.

    A domain appearing 2+ times means the operator owns multiple
    storefronts on that site — strong chain signal.
    """
    c: Counter[str] = Counter()
    for lead in leads:
        d = _domain_of(lead.website_url)
        if d:
            c[d] += 1
    return c


def score_lead(lead: Lead, *, domain_count: int) -> tuple[int, list[str]]:
    """Return (score 0-100, list of reasons applied) for one lead.

    `domain_count` is how many leads in the cohort share this lead's
    website domain. Caller computes once via `domain_counts(leads)`
    and passes per-lead.
    """
    score = 50
    reasons: list[str] = ["base=50"]

    # ── Reachability ────────────────────────────────────────────────────
    if lead.contact_email:
        score += 15
        reasons.append("+15 has_email")
        if lead.contact_email_source == "footer":
            score += 5
            reasons.append("+5 email_scraped_from_site")
    else:
        reasons.append("no_email")

    # ── Platform fit ────────────────────────────────────────────────────
    platform = lead.pos_platform or lead.current_site_status
    if platform:
        bonus = _PLATFORM_BONUS.get(platform, 0)
        if bonus:
            sign = "+" if bonus > 0 else ""
            score += bonus
            reasons.append(f"{sign}{bonus} platform_{platform}")

    # ── Independent vs chain (multi-signal) ─────────────────────────────
    if domain_count >= 3:
        score -= 30
        reasons.append("-30 chain_3plus_locations_same_domain")
    elif domain_count == 2:
        score -= 10
        reasons.append("-10 dual_location_same_domain")
    else:
        score += 20
        reasons.append("+20 independent_unique_domain")

    if _matches_chain(lead.business_name):
        score -= 30
        reasons.append("-30 chain_name_match")

    # ── Worst-case quality floor ────────────────────────────────────────
    # No website AND no email = nothing the drafter can use. Cap low.
    if platform == "none" and not lead.contact_email:
        score = min(score, 25)
        reasons.append("cap=25 unreachable")

    score = max(0, min(100, score))
    return score, reasons
