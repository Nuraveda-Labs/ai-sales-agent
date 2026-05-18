# Glitch Budz — cold-email creative brief

**For:** the creative writer / copy person reviewing our outbound voice.
**Goal:** rewrite or refine the email copy that ships to Toronto cannabis
retailers. The system is functioning — what it needs is sharper copy.

---

## What we sell

A productized cannabis e-commerce SaaS for independent Canadian
retailers. We give them a real React storefront with mobile product
pages, Interac + crypto checkout, customer accounts, branded order
emails, AGCO-aligned click-and-collect, and AI SEO — at a fraction of
what an agency would charge. **$999 setup + $99/month flat. No
transaction fees.** *(Pricing never goes in the email body — that's a
relief on the call, not a hook in the inbox.)*

The reference build (a real working store) lives at
[exotic420budz.com](https://exotic420budz.com) and the marketing site
is at [grow.example.com/budz](https://grow.example.com/budz).

---

## How we bucket stores

Every lead is automatically classified by the e-commerce / POS platform
powering their website. The pitch differs by stack — telling a Dutchie
shop "you have no online menu" is wrong (they do); telling a
Squarespace shop "your iframe is invisible to AI" is wrong (they don't
have one).

Detection is automated: we fetch each lead's website, scan for known
signatures (`cdn.dutchie.com` → Dutchie, `wixstatic.com` → Wix, etc.),
and bucket into one of seven `pos_platform` values.

| Bucket       | What it actually is                                              | Lead count |
|--------------|------------------------------------------------------------------|------------|
| **brochure** | Squarespace / Wix / WordPress with **no** online ordering         | 146        |
| **none**     | No website found / fetch failed / blank page                      | 62         |
| **custom**   | Hand-rolled or custom-CMS site, no platform signature             | 53         |
| **dutchie**  | Dutchie iframe menu — functional ordering, but AI-invisible       | 31         |
| **blaze**    | Blaze POS + e-commerce on a `shop.*` subdomain                    | 27         |
| **shopify**  | Shopify cannabis-store templates (usually chains)                 | 14         |
| **tendypos** | TendyPOS via UnoApp (Toronto-specific, rare)                      | 1          |
| *(skipped)*  | Multi-location chains (Tokyo Smoke, Canna Cabana, Spiritleaf, …)  | 244 paused |

Each bucket has its own emotional frame:

- **none / brochure** → they're missing online ordering entirely. Pitch:
  *get them online.*
- **dutchie / blaze / tendypos** → they have a working POS, but it locks
  them into a generic UX and a vendor-controlled checkout. Pitch:
  *real storefront on top, not a replacement.*
- **custom** → already invested in their site. Pitch:
  *storefront polish + AI SEO they're missing.*
- **shopify** → usually chains; deprioritized.

---

## What recipes (hooks) we're using per bucket

Within each bucket we ship multiple **hook angles** for variety. The
same lead always renders the same hook (deterministic per-lead hash) so
when reply data lands, we can attribute open/reply rate per hook
cleanly.

There are **9 distinct hook angles** in rotation across **27 hook
instances** per bucket. Each angle is summarised below; full text
lives in `src/ai_marketing_stack_sales_playbook/recipes.py`.

| Hook angle             | What it argues                                                                              | Buckets it fires in              |
|------------------------|---------------------------------------------------------------------------------------------|----------------------------------|
| `chains_have`          | Chains like Tokyo Smoke + Spiritleaf get cited in ChatGPT/Perplexity for cannabis Toronto. You don't.       | every bucket                     |
| `walk_by_customer`     | The customer 3 blocks from your shop Googles "cannabis near me," sees the chain, walks there.              | brochure, none                   |
| `repeat_activation`    | Most cannabis revenue is repeats. No online checkout → no email list → no way to bring them back.           | brochure                         |
| `phone_calls`          | "Do you have X strain in stock?" calls all day. A real online menu eats most of those calls.                | brochure, dutchie, blaze, tendypos |
| `time_budget`          | Agencies quote $50k+ over 4-month builds. Indies can't justify it. We deliver the same in 48 hours.         | brochure, dutchie, tendypos, none |
| `time_not_money`       | Even with the budget, you don't have 20 hrs/week to maintain a site. We host, fix, update.                  | brochure, dutchie, blaze, tendypos |
| `switching_cost_safe`  | Not asking you to switch off Dutchie/Blaze/TendyPOS. We add a marketing site on top of your existing checkout. | dutchie, blaze, tendypos       |
| `ai_shift`             | Shoppers are skipping Google for ChatGPT/Perplexity. Hosted templates aren't indexed.                       | blaze, custom                    |
| `founder_proof`        | Built exotic420budz.com to prove this works. Same stack i'd build for you.                                  | custom                           |

---

## Sample email — what a real shop owner receives

This is what a real Toronto cannabis retailer would see in their inbox
right now. The drafter substitutes `{shop_name}` and `{website_url}`
automatically per-lead. This example is for **Exclusives Cannabis**, a
Squarespace brochure shop on `exclusivescannabis.ca`, drafted with the
`brochure:repeat_activation` hook.

```
From:    Tejas Karan Agrawal <support@example.com>
To:      yongestreet@exclusivescannabis.ca
Subject: where Exclusives Cannabis's repeats are going

hey,

Exclusives Cannabis's site at exclusivescannabis.ca doesn't capture
customer emails — there's no checkout. that means no way to bring
regulars back, no drip campaigns.

i build storefronts with real checkout + email capture + branded
lifecycle emails (placed, paid, shipped, delivered). your repeats
start coming back.

30-sec: exotic420budz.com
full breakdown + pricing: grow.example.com/budz
15 min: calendly.com/glitchexecutor-support/30min

— Tejas Karan Agrawal

---
an open-source project (Nuraveda) · 77 Huntley St, Toronto, ON
reply 'stop' to unsubscribe
```

**Sent via** the operator's real Google Workspace mailbox
(`support@example.com`) using direct Gmail Send, not a
transactional service. The recipient gets a real-Gmail send experience
(headers, threading, replies) — looks like a colleague typed it, not a
marketing blast.

---

## Voice rules currently locked in

These exist to keep every iteration from drifting back into B2B-pitch-
deck voice. Bend them deliberately if needed; don't bend them by accident.

- **Plain text only.** No HTML, no images, no styled buttons.
- **Lowercase prose.** Proper nouns kept cased: Tokyo Smoke, Spiritleaf,
  Dutchie, Blaze, TendyPOS, ChatGPT, Perplexity, Google AI Overviews,
  Toronto, Interac.
- **First-person singular** ("i", "i build", "i fix"). Tejas is a solo
  founder, not a team. Never "we" / "our team".
- **"hey," opener** every time. No "Dear" / "Hi there" / "Greetings".
- **30–50 word body.** Trey's email in the Proposify case study was 30
  words and converted; ours stretches to 50 when context demands.
- **Sign off "— Tejas Karan Agrawal"** — the render layer appends this
  + the CASL footer automatically. Don't include them in the recipe body.
- **Three CTA links inline**, in this order:
    1. `30-sec: exotic420budz.com` (lowest commitment, highest click)
    2. `full breakdown + pricing: grow.example.com/budz`
    3. `15 min: calendly.com/glitchexecutor-support/30min`
- **No prices in the body.** The only dollar figure allowed is the
  `$50k+` agency-cost reference (it anchors the gap, not our offer).
  Glitch Budz pricing reveals on the booking call as a relief.
- **Banned phrases:** "we are excited", "leverage", "synergy", "circle
  back", "reach out", "fraction of agency cost" (cliché),
  "chain-quality storefront" (cliché), exclamation marks, emoji.

---

## What you (the creative) can change

The system is built so copy changes ship in minutes, not days.

1. **Open** `ai_marketing_stack-sales-agent-private/src/ai_marketing_stack_sales_playbook/recipes.py`.
   Each `Hook(...)` block is one variant. Edit the `subjects`, `opener`,
   and `body` fields directly.
2. **Run** `PYTHONPATH=src python3 -m sales_agent.agent.run_draft_batch --limit 5 --preview`
   to render fresh drafts with the new copy against real leads.
3. **A/B preview** to the operator's personal Gmail before any cohort
   ships. The system can fire a single test send to verify tone +
   inbox-tab placement on demand.
4. **Commit + push** to the private repo. Future drafts pick up the new
   copy automatically.

Already-sent emails stay as-is in the audit log; nothing rewrites
history.

## What's measurable

Once 50+ emails have shipped per hook, we'll have:

- **Open rate** per hook + per subject variant (Resend dashboard +
  Gmail send analytics)
- **Reply rate** per hook (manual today, IMAP-poller automation soon)
- **Click-through** to demo / landing / Calendly per hook (Resend +
  GA4 on the landing page)
- **Demo-booked rate** per hook (HubSpot deal stage transitions:
  Sent → Replied → Demo Booked)

Per-hook attribution stays clean because the drafter writes the hook
identifier into `email_drafts.recipe_key` (e.g., `brochure:repeat_activation`)
at draft time. No need to tag emails after the fact.

---

*Generated for the Glitch Budz creative review, April 2026.*
