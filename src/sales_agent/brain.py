"""BSK-003 → brain bridge (GROW-BIND-2, 2026-05-17).

Mirrors every Sales agent memory write onto the shared
`brain-mcp` so sibling agents on the same brand can see what
Sales just did (drafts produced, sends executed, lead state moves).

This is **additive**: the existing `sales_agent.agent_memory`
Postgres table stays as the agent's private vector-searchable
memory. The brain mirror is the sibling-visible coordination layer.

Wiring contract:
  - Env `BRAIN_MCP_URL` overrides the brain URL.
  - Env `SALES_AGENT_BRAND_SLUG` names the brand the Sales agent is
    currently running for (e.g. `example-tenant`). The bridge then
    looks up `BRAIN_TOKEN_BSK_003_<UPPER_SNAKED_SLUG>` from env to
    get the bearer.
  - Backward-compat fallback: bare `BRAIN_TOKEN_BSK_003` if it's set
    (single-token dev setups).
  - Unconfigured (no slug + no legacy token) → silent no-op. The
    agent's primary data path (`sales_agent.agent_memory` insert)
    is unaffected.
  - All brain calls are fire-and-forget; brain failures NEVER block
    or fail the local insert.

Per the brands × agents matrix in memory (`brands_agent_matrix.md`),
BSK-003 Sales is currently enrolled only for `example-tenant`. The
env-driven design keeps the bridge ready for future enrolments
without code change — drop the new token into the consolidated `.env`
and switch `SALES_AGENT_BRAND_SLUG` per deployment.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from grow_platform.brain import BrainAuthError, BrainClient, BrainError
from grow_platform.brain.limits import cap_payload

log = logging.getLogger(__name__)

_DEFAULT_BRAIN_URL = "http://127.0.0.1:3107/mcp"
_BRAIN_TOKEN_PREFIX = "BRAIN_TOKEN_BSK_003_"
_BRAIN_TOKEN_LEGACY = "BRAIN_TOKEN_BSK_003"
_BRAIN_URL_ENV = "BRAIN_MCP_URL"
_BRAND_SLUG_ENV = "SALES_AGENT_BRAND_SLUG"

_NON_ENV_CHARS = re.compile(r"[^A-Z0-9_]")


def _slug_to_env_suffix(brand_slug: str | None) -> str | None:
    if not brand_slug:
        return None
    s = brand_slug.strip().upper().replace("-", "_")
    s = _NON_ENV_CHARS.sub("", s)
    return s or None


def _configured_brand_slug() -> str | None:
    return os.environ.get(_BRAND_SLUG_ENV) or None


def _brain_url() -> str:
    return os.environ.get(_BRAIN_URL_ENV, _DEFAULT_BRAIN_URL)


def _brain_token() -> str | None:
    """Resolve the BSK-003 bearer.

    Priority:
      1. Per-brand `BRAIN_TOKEN_BSK_003_<SLUG_UPPER>` keyed off
         `SALES_AGENT_BRAND_SLUG` env.
      2. Legacy bare `BRAIN_TOKEN_BSK_003` (pre-BIND-2 single-token
         setups).
    """
    slug = _configured_brand_slug()
    suffix = _slug_to_env_suffix(slug)
    if suffix is not None:
        per_brand = os.environ.get(_BRAIN_TOKEN_PREFIX + suffix)
        if per_brand:
            return per_brand
    legacy = os.environ.get(_BRAIN_TOKEN_LEGACY)
    return legacy or None


def brain_available() -> bool:
    """True when a BSK-003 brain token resolves under the current
    `SALES_AGENT_BRAND_SLUG` (or the legacy bare token).

    Callers use this for diagnostics (e.g. log on startup); the
    bridge functions below also check internally so it's safe to
    call them blind — they no-op when unconfigured.
    """
    return _brain_token() is not None


def _summarize_for_brain(text: str | None, max_chars: int = 240) -> str:
    """Flatten newlines + clip to a readable one-liner suitable for
    `team_state` and `recent_activity`."""
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


async def mirror_memory_to_brain(
    *,
    kind: str,
    content: str,
    lead_id: str | None,
    recipe_key: str | None,
    outcome: str | None,
    metadata: dict[str, Any] | None,
) -> None:
    """Best-effort mirror of one `sales_agent.agent_memory` insert to
    the brain.

    Called from `db/repos.AgentMemoryRepo.insert` after the local
    insert succeeds. Errors are caught + logged at WARNING; the
    local insert is never rolled back on brain failure.

    No-ops silently when the BSK-003 brain token isn't configured —
    keeps the agent runnable in dev / on a fresh box without brain
    plumbing.
    """
    token = _brain_token()
    if token is None:
        return

    payload: dict[str, Any] = {
        "kind": kind,
        "lead_id": str(lead_id) if lead_id is not None else None,
    }
    if recipe_key is not None:
        payload["recipe_key"] = recipe_key
    if outcome is not None:
        payload["outcome"] = outcome
    if metadata is not None:
        payload["metadata"] = metadata

    try:
        async with BrainClient(url=_brain_url(), token=token) as brain:
            await brain.append_activity(
                action=f"memory.{kind}" if kind else "memory.write",
                summary=_summarize_for_brain(content),
                subject=str(lead_id) if lead_id is not None else None,
                payload=cap_payload(payload),
                agent_sku="BSK-003",
            )
    except BrainAuthError:
        slug = _configured_brand_slug() or "<unset>"
        suffix = _slug_to_env_suffix(slug) or "<unset>"
        log.warning(
            "sales_agent brain mirror auth failed (BSK-003, slug=%r); "
            "check env var %s%s (or legacy %s)",
            slug, _BRAIN_TOKEN_PREFIX, suffix, _BRAIN_TOKEN_LEGACY,
        )
    except BrainError as e:
        log.warning("sales_agent brain mirror failed: %s", e)
    except Exception:  # noqa: BLE001 — never let brain take down the agent
        log.exception("sales_agent brain mirror raised unexpectedly")


def schedule_brain_mirror(
    *,
    kind: str,
    content: str,
    lead_id: str | None = None,
    recipe_key: str | None = None,
    outcome: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Schedule a brain mirror on the running event loop.

    Called by `AgentMemoryRepo.insert` after a successful local
    insert. Mirrors the BIND-1 fire-and-forget convention so brain
    mirroring is invisible to the agent's insert latency.
    """
    if not brain_available():
        return
    asyncio.ensure_future(
        mirror_memory_to_brain(
            kind=kind,
            content=content,
            lead_id=lead_id,
            recipe_key=recipe_key,
            outcome=outcome,
            metadata=metadata,
        )
    )
