"""Outbound + inbound email plumbing (Gmail API).

Sends from a real Google Workspace mailbox so replies thread naturally and
the operator's existing inbox is the reply surface. No transactional ESP.

Modules (to be implemented in v1):
- `gmail`   — send / list / fetch via Gmail API with OAuth refresh.
- `tracker` — open-pixel handler + reply detector that polls the sender's
              inbox for new messages on threads we own.
"""
