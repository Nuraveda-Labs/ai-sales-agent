"""Enrichment — fill the fields a personalized email needs.

Reads `sales_agent.leads` rows that are `status='new'`, fetches each shop's
website, classifies the `current_site_status` enum
(`none / linktree / builder / lightspeed / custom`), and resolves a contact
email by scraping the footer, then the IG bio, then falling back to
MX-verified pattern guesses.

Modules (to be implemented in v1):
- `site_detector`  — classifies the website type from HTML signatures.
- `contact_finder` — multi-strategy contact-email resolver.
"""
