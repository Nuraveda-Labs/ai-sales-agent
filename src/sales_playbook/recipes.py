"""Calibrated recipes for Glitch Budz outbound — v9 (creative-rewrite pass).

This pass integrates the creative writer's rewrite from Apr 30 2026.
Punchier, tighter, 30-50 words. Markdown link syntax stripped to bare
hostnames (recipes are plain text only — see `voice rules` below).

Voice rules (locked):
- Lead with the STOREFRONT product. AI SEO is a bonus, not the headline.
- Lowercase prose; proper nouns kept cased (Tokyo Smoke, Spiritleaf,
  Dutchie, Blaze, TendyPOS, ChatGPT, Perplexity, Toronto, Interac).
- "hey," opener every time.
- First-person singular ("i").
- 30-50 word body. Plain text. No HTML, no markdown links.
- Three CTAs in this exact order:
    1. 30-sec: exotic420budz.com
    2. full breakdown + pricing: grow.example.com/budz
    3. 15 min: calendly.com/glitchexecutor-support/30min
- Sign off "— Tejas Karan Agrawal" — appended by the render layer.
- No prices in body except "$50k+" agency reference (anchors gap).
- Banned phrases: "we are excited", "leverage", "synergy", "circle
  back", "reach out", "fraction of agency cost" (cliché),
  "chain-quality storefront" (cliché), exclamation marks, emoji.

Personalization slots (from drafter):
  {shop_name}     — always
  {website_url}   — bare hostname, e.g. "exclusivescannabis.ca"
  {city}          — falls back to "your area" when missing
"""

from __future__ import annotations

from sales_agent.agent.recipes_stub import Hook, Recipe


_CALENDLY = "calendly.com/glitchexecutor-support/30min"
_DEMO = "exotic420budz.com"
_LANDING = "grow.example.com/budz"


def _ctas(first_label: str = "30-sec") -> str:
    return (
        f"{first_label}: {_DEMO}\n"
        f"full breakdown + pricing: {_LANDING}\n"
        f"15 min: {_CALENDLY}\n"
    )


# ─── BROCHURE  (Squarespace / Wix / WP brochure, no online ordering) ────────

_BROCHURE_HOOKS = (
    Hook(
        name="repeat_activation",
        subjects=(
            "where your repeats are disappearing",
            "no checkout = no email list",
        ),
        opener="hey,",
        body=(
            "your site at {website_url} has no checkout and no email "
            "capture. that means your regulars have zero reason to come "
            "back after they leave the store.\n\n"
            "i build real storefronts that collect emails and send branded "
            "lifecycle emails so your repeats actually return.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="walk_by_customer",
        subjects=(
            "the customer walking past your door",
            "cannabis near me — you're not showing up",
        ),
        opener="hey,",
        body=(
            "someone 3 blocks from {shop_name} searches \"cannabis near "
            "me\" right now. they see Tokyo Smoke or Spiritleaf, not you.\n\n"
            "i build proper storefronts that actually show up and convert "
            "local search traffic.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="phone_calls",
        subjects=(
            "all those \"do you have X in stock?\" calls",
            "stop answering the same call all day",
        ),
        opener="hey,",
        body=(
            "how many times a day do you get calls asking if you have a "
            "specific strain or product in stock?\n\n"
            "i build real online menus with checkout that answer most of "
            "those questions before the phone even rings.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="time_budget",
        subjects=(
            "the $50k+ agency quote you probably got",
            "$50k agency vs 48 hours",
        ),
        opener="hey,",
        body=(
            "agencies quote most Toronto cannabis shops $50k+ and 4 months "
            "to build a proper storefront.\n\n"
            "i deliver the same quality in 48 hours for a fraction of "
            "that.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="chains_have",
        subjects=(
            "why Tokyo Smoke shows up but you don't",
            "ChatGPT mentions the chains, not you",
        ),
        opener="hey,",
        body=(
            "when someone asks ChatGPT or Perplexity for cannabis in "
            "Toronto, the big chains like Tokyo Smoke and Spiritleaf get "
            "mentioned. independent shops rarely do.\n\n"
            "i build storefronts that actually get picked up by ai.\n\n"
            f"{_ctas()}"
        ),
    ),
)


# ─── DUTCHIE  (iframe menu — your customers leave your brand to check out) ──

_DUTCHIE_HOOKS = (
    Hook(
        name="switching_cost_safe",
        subjects=(
            "keeping Dutchie while getting a real storefront",
            "Dutchie + a real storefront on top",
        ),
        opener="hey,",
        body=(
            "your Dutchie menu works for ordering but it's invisible to "
            "search engines and ai tools. customers can't easily find "
            "you.\n\n"
            "i add a real React storefront on top of your existing pos — "
            "no switching needed, much better customer experience.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="phone_calls",
        subjects=(
            "still getting stock check phone calls?",
            "Dutchie isn't catching all the orders",
        ),
        opener="hey,",
        body=(
            "even with Dutchie, you're probably still getting \"do you "
            "have this strain?\" calls all day.\n\n"
            "i build a proper storefront that shows real-time inventory "
            "and lets people order online, cutting down those calls.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="chains_have",
        subjects=(
            "why Tokyo Smoke shows up but you don't",
            "ChatGPT mentions the chains, not you",
        ),
        opener="hey,",
        body=(
            "when someone asks ChatGPT or Perplexity for cannabis in "
            "Toronto, the big chains like Tokyo Smoke and Spiritleaf get "
            "mentioned. independent shops rarely do.\n\n"
            "i build storefronts that actually get picked up by ai — on "
            "top of your existing Dutchie checkout.\n\n"
            f"{_ctas()}"
        ),
    ),
)


# ─── BLAZE  (shop.* hosted-template — customers land on a Blaze template) ───

_BLAZE_HOOKS = (
    Hook(
        name="switching_cost_safe",
        subjects=(
            "keeping Blaze while getting a real storefront",
            "Blaze + a real storefront on top",
        ),
        opener="hey,",
        body=(
            "your Blaze shop works for ordering but it's invisible to "
            "search engines and ai tools. customers can't easily find "
            "you.\n\n"
            "i add a real React storefront on top of your existing pos — "
            "no switching needed, much better customer experience.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="phone_calls",
        subjects=(
            "still getting stock check phone calls?",
            "Blaze isn't catching all the orders",
        ),
        opener="hey,",
        body=(
            "even with Blaze, you're probably still getting \"do you have "
            "this strain?\" calls all day.\n\n"
            "i build a proper storefront that shows real-time inventory "
            "and lets people order online, cutting down those calls.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="ai_shift",
        subjects=(
            "your site isn't showing up in ChatGPT or Perplexity",
            "Blaze templates aren't indexed by ai",
        ),
        opener="hey,",
        body=(
            "shoppers are increasingly asking ChatGPT and Perplexity for "
            "\"best cannabis Toronto\" instead of Google.\n\n"
            "most template or hosted sites aren't properly indexed by ai "
            "tools. i fix that — without you leaving Blaze.\n\n"
            f"{_ctas()}"
        ),
    ),
)


# ─── TENDYPOS  (UnoApp-hosted; usually paired with a Squarespace landing) ───

_TENDYPOS_HOOKS = (
    Hook(
        name="switching_cost_safe",
        subjects=(
            "keeping TendyPOS while getting a real storefront",
            "TendyPOS + a real storefront on top",
        ),
        opener="hey,",
        body=(
            "your TendyPOS shop works for ordering but it's invisible to "
            "search engines and ai tools. customers can't easily find "
            "you.\n\n"
            "i add a real React storefront on top of your existing pos — "
            "no switching needed, much better customer experience.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="phone_calls",
        subjects=(
            "still getting stock check phone calls?",
            "TendyPOS isn't catching all the orders",
        ),
        opener="hey,",
        body=(
            "even with TendyPOS, you're probably still getting \"do you "
            "have this strain?\" calls all day.\n\n"
            "i build a proper storefront that shows real-time inventory "
            "and lets people order online, cutting down those calls.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="time_budget",
        subjects=(
            "the $50k+ agency quote you probably got",
            "$50k agency vs 48 hours",
        ),
        opener="hey,",
        body=(
            "agencies quote most Toronto cannabis shops $50k+ and 4 months "
            "to build a proper storefront on top of their pos.\n\n"
            "i deliver the same quality in 48 hours for a fraction of "
            "that. TendyPOS keeps inventory.\n\n"
            f"{_ctas()}"
        ),
    ),
)


# ─── NONE  (no website at all) ──────────────────────────────────────────────

_NONE_HOOKS = (
    Hook(
        name="walk_by_customer",
        subjects=(
            "the customer walking past your door",
            "cannabis near me — you're not showing up",
        ),
        opener="hey,",
        body=(
            "someone 3 blocks from {shop_name} searches \"cannabis near "
            "me\" right now. they see Tokyo Smoke or Spiritleaf, not "
            "you.\n\n"
            "i build proper storefronts that actually show up and convert "
            "local search traffic.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="time_budget",
        subjects=(
            "the $50k+ agency quote you probably got",
            "$50k agency vs 48 hours",
        ),
        opener="hey,",
        body=(
            "agencies quote most Toronto cannabis shops $50k+ and 4 months "
            "to build a proper storefront.\n\n"
            "i deliver the same quality in 48 hours for a fraction of "
            "that.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="chains_have",
        subjects=(
            "why Tokyo Smoke shows up but you don't",
            "ChatGPT mentions the chains, not you",
        ),
        opener="hey,",
        body=(
            "when someone asks ChatGPT or Perplexity for cannabis in "
            "Toronto, the big chains like Tokyo Smoke and Spiritleaf get "
            "mentioned. independent shops rarely do.\n\n"
            "i build storefronts that actually get picked up by ai.\n\n"
            f"{_ctas()}"
        ),
    ),
)


# ─── SHOPIFY  (mostly chains; recipe exists, scoring benches them out) ──────

_SHOPIFY_HOOKS = (
    Hook(
        name="ai_shift",
        subjects=(
            "Shopify cannabis templates aren't indexed by ai",
            "your site isn't showing up in ChatGPT",
        ),
        opener="hey,",
        body=(
            "shoppers are increasingly asking ChatGPT and Perplexity for "
            "\"best cannabis Toronto\" instead of Google.\n\n"
            "most Shopify cannabis templates aren't properly indexed by ai "
            "tools. i build cannabis-native storefronts that are.\n\n"
            f"{_ctas()}"
        ),
    ),
)


# ─── CUSTOM  (catch-all; lead with the gap) ─────────────────────────────────

_CUSTOM_HOOKS = (
    Hook(
        name="founder_proof",
        subjects=(
            f"same stack i built for {_DEMO}",
            "built exotic420budz to prove this works",
        ),
        opener="hey,",
        body=(
            f"i built {_DEMO} from scratch with the exact same tech i'd "
            "use for {shop_name}.\n\n"
            "real React storefront, proper checkout, customer accounts, "
            "and ai seo that actually works.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="ai_shift",
        subjects=(
            "your site isn't showing up in ChatGPT or Perplexity",
            "ai search is eating Google for cannabis",
        ),
        opener="hey,",
        body=(
            "shoppers are increasingly asking ChatGPT and Perplexity for "
            "\"best cannabis Toronto\" instead of Google.\n\n"
            "most template or custom sites aren't properly indexed by ai "
            "tools. i fix that.\n\n"
            f"{_ctas()}"
        ),
    ),
    Hook(
        name="chains_have",
        subjects=(
            "why Tokyo Smoke shows up but you don't",
            "ChatGPT mentions the chains, not you",
        ),
        opener="hey,",
        body=(
            "when someone asks ChatGPT or Perplexity for cannabis in "
            "Toronto, the big chains like Tokyo Smoke and Spiritleaf get "
            "mentioned. independent shops rarely do.\n\n"
            "i build storefronts that actually get picked up by ai.\n\n"
            f"{_ctas()}"
        ),
    ),
)


# ─── Recipe library ──────────────────────────────────────────────────────────

RECIPES: dict[str, Recipe] = {
    "none":     Recipe(key="none",     hooks=_NONE_HOOKS),
    "brochure": Recipe(key="brochure", hooks=_BROCHURE_HOOKS),
    "dutchie":  Recipe(key="dutchie",  hooks=_DUTCHIE_HOOKS),
    "blaze":    Recipe(key="blaze",    hooks=_BLAZE_HOOKS),
    "tendypos": Recipe(key="tendypos", hooks=_TENDYPOS_HOOKS),
    "shopify":  Recipe(key="shopify",  hooks=_SHOPIFY_HOOKS),
    "custom":   Recipe(key="custom",   hooks=_CUSTOM_HOOKS),
}
