"""Thin HubSpot v3 REST client over httpx.

Picked raw httpx over `hubspot-api-client` because the SDK is sync (would
need `asyncio.to_thread` everywhere), heavy install, and we only call ~10
endpoints. The REST surface is documented at developers.hubspot.com/docs/api.

Auth is a Bearer header carrying the Private App token. PATs do not need
refresh — they're issued from the HubSpot UI and rotated there.

All calls go through `request()` which retries 429 / 5xx with exponential
backoff (tenacity). HubSpot's rate limit is 100 req/10s on the standard
tier; at our v1 volume (<50 leads/day) we'll never approach it, but the
retry logic is there for the inevitable transient 502.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from sales_agent.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.hubapi.com"

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Lazily build the shared httpx client. Pool stays open for the process lifetime."""
    global _client
    if _client is None:
        if not settings.hubspot_pat:
            raise RuntimeError("HUBSPOT_PAT not set; cannot call HubSpot")
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {settings.hubspot_pat}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(20.0, connect=5.0),
        )
    return _client


async def aclose() -> None:
    """Close the shared client. Call on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class HubSpotError(RuntimeError):
    """Raised when HubSpot returns a non-retryable 4xx (auth, validation, conflict)."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"HubSpot {status_code}: {body[:500]}")
        self.status_code = status_code
        self.body = body


_RETRYABLE = (httpx.TransportError, httpx.ReadTimeout, httpx.ConnectTimeout)


async def request(
    method: str, path: str, *,
    json: Any | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    """Issue a HubSpot REST call with retries on transport failures + 429 / 5xx.

    Returns the JSON-decoded body on success. Raises HubSpotError for
    terminal 4xx so callers can decide whether to swallow (sync.* swallows
    everything; pipelines.* surfaces).
    """
    client = _get_client()

    async for attempt in AsyncRetrying(
        wait=wait_exponential(multiplier=1, min=1, max=15),
        stop=stop_after_attempt(4),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    ):
        with attempt:
            resp = await client.request(method, path, json=json, params=params)

            # Retryable HTTP statuses — raise httpx error so tenacity catches.
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                raise httpx.TransportError(
                    f"HubSpot {resp.status_code}: {resp.text[:200]}"
                )

            # Terminal 4xx — surface as HubSpotError, no retry.
            if 400 <= resp.status_code < 500:
                raise HubSpotError(resp.status_code, resp.text)

            return resp.json() if resp.content else None
