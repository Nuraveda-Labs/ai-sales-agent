"""Discovery — find prospects.

Pulls cannabis retailers (or any vertical) from Google Maps Places API in a
configurable polygon, cross-checks against the AGCO licensee registry to
filter to legally-operating shops, and writes new rows to `sales_agent.leads`.

Modules (to be implemented in v1):
- `google_places` — per-neighbourhood Places API search.
- `agco`          — Cannabis Retail Store registry cross-check.
"""
