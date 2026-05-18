"""Pipeline + stage definitions for the Glitch Budz HubSpot pipeline.

`PIPELINE_STAGES` is the source of truth: `pipelines.ensure_pipeline()`
creates exactly these stages in this order, and `STATUS_TO_STAGE_LABEL`
maps Postgres `leads.status` values onto them.

Note: `opened` deliberately maps to `Sent`. We don't surface opens in
HubSpot timeline (decision: sends + replies only). Opens stay in Postgres.

`paused` maps to `None` — we leave the deal at whatever stage it was at
and let the operator decide manually. The deal is *not* moved to a "Paused"
stage because that would clutter the pipeline view; pauses are tracked in
Postgres only.
"""

from __future__ import annotations

# (label, probability_in_pct, is_closed, is_won) — HubSpot defines stages
# with a probability + a closedWon flag. "open" stages have probability < 1
# and isClosed = false. Closed Won has probability 1 + isClosed True + isWon
# True. Closed Lost has probability 0 + isClosed True + isWon False.
PIPELINE_STAGES: list[tuple[str, float, bool, bool]] = [
    ("Discovered",   0.05, False, False),
    ("Enriched",     0.10, False, False),
    ("Drafted",      0.15, False, False),
    ("Sent",         0.20, False, False),
    ("Replied",      0.40, False, False),
    ("Demo Booked",  0.60, False, False),
    ("Pilot Signed", 0.85, False, False),
    ("Closed Won",   1.00, True,  True),
    ("Closed Lost",  0.00, True,  False),
]

# leads.status → HubSpot stage label. None means "don't move the stage".
STATUS_TO_STAGE_LABEL: dict[str, str | None] = {
    "new":       "Discovered",
    "enriched":  "Enriched",
    "scored":    "Enriched",
    "drafted":   "Drafted",
    "sent":      "Sent",
    "opened":    "Sent",       # opens not surfaced in HubSpot
    "replied":   "Replied",
    "booked":    "Demo Booked",
    "paused":    None,         # leave the deal where it is
    "dead":      "Closed Lost",
}
