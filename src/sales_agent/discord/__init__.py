"""Discord HITL surface.

Long-lived gateway connection (run as a separate process, see `bot.py`).
Posts every drafted email as an embed in a configured channel; reactions
drive the approval flow:

    ✅  send
    ❌  kill the draft + mark the lead `paused`
    🖊️  request edit (operator replies in-thread with corrected copy)

Slash commands handle bulk operations (`/leads new`, `/leads stats`,
`/recipes lift`, `/autonomy`).

Modules (to be implemented in v1):
- `bot`      — discord.py Client bootstrap.
- `handlers` — slash + reaction handlers.
- `auth`     — DISCORD_ADMIN_USER_IDS guard.
"""
