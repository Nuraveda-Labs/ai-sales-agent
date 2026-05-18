"""Google Places API (New) v1 client with SA impersonation.

Auth flow:
- Application Default Credentials pick up the box's attached SA
  (`<projectnum>-compute@developer.gserviceaccount.com`).
- That SA impersonates `glitch-vertex-ai@…iam.gserviceaccount.com` via
  `google.auth.impersonated_credentials.Credentials` so calls are
  attributed to the operations SA.
- Refresh is automatic when the cached token is invalid; the wrapper
  surfaces token-refresh errors as RuntimeError.

Field mask is sent on every request (`X-Goog-FieldMask`) — Places API
(New) bills per requested field, so masking down to what we actually
persist keeps cost predictable.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from google.auth import default as google_default
from google.auth.impersonated_credentials import Credentials as ImpersonatedCredentials
from google.auth.transport.requests import Request

from sales_agent.config import settings

logger = logging.getLogger(__name__)

PLACES_BASE = "https://places.googleapis.com/v1"

# Default mask used by the discovery worker. Includes everything we map
# into `sales_agent.leads`. Add more fields here only when we have a
# downstream consumer for them — every added field costs more per call.
DEFAULT_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.addressComponents,"
    "places.location,"
    "places.nationalPhoneNumber,"
    "places.websiteUri,"
    "places.types,"
    "places.businessStatus,"
    "nextPageToken"
)

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class GooglePlacesClient:
    """Async Places API (New) client. Construct once per process."""

    def __init__(
        self,
        *,
        target_sa: str,
        project_id: str,
        field_mask: str = DEFAULT_FIELD_MASK,
        timeout_s: float = 30.0,
    ) -> None:
        self._target_sa = target_sa
        self._project_id = project_id
        self._field_mask = field_mask
        self._creds: ImpersonatedCredentials | None = None
        self._client = httpx.AsyncClient(
            base_url=PLACES_BASE,
            timeout=httpx.Timeout(timeout_s, connect=5.0),
        )

    # ── Auth ────────────────────────────────────────────────────────────────

    def _credentials(self) -> ImpersonatedCredentials:
        if self._creds is None:
            source, _ = google_default(scopes=[CLOUD_PLATFORM_SCOPE])
            self._creds = ImpersonatedCredentials(
                source_credentials=source,
                target_principal=self._target_sa,
                target_scopes=[CLOUD_PLATFORM_SCOPE],
                lifetime=3600,  # max for impersonated tokens
            )
        if not self._creds.valid:
            try:
                self._creds.refresh(Request())
            except Exception as e:
                raise RuntimeError(
                    f"failed to mint impersonated token for {self._target_sa}: {e}"
                ) from e
        return self._creds

    def _headers(self) -> dict[str, str]:
        creds = self._credentials()
        return {
            "Authorization":      f"Bearer {creds.token}",
            "X-Goog-User-Project": self._project_id,
            "X-Goog-FieldMask":    self._field_mask,
            "Content-Type":        "application/json",
        }

    # ── Endpoints ───────────────────────────────────────────────────────────

    async def search_text(
        self,
        query: str,
        *,
        page_size: int = 20,
        page_token: str | None = None,
        included_type: str | None = None,
        location_bias: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Single page of `places:searchText`.

        Pass `page_token` from the previous response to get the next page.
        Places API (New) caps `page_size` at 20 and exposes at most 60
        results across 3 pages per query.
        """
        body: dict[str, Any] = {"textQuery": query, "pageSize": page_size}
        if page_token:
            body["pageToken"] = page_token
        if included_type:
            body["includedType"] = included_type
        if location_bias:
            body["locationBias"] = location_bias

        resp = await self._client.post(
            "/places:searchText", headers=self._headers(), json=body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Places searchText {resp.status_code}: {resp.text[:500]}"
            )
        return resp.json()

    async def search_text_all(
        self, query: str, *, max_pages: int = 3, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Page through `places:searchText` until exhausted or `max_pages` hit."""
        out: list[dict[str, Any]] = []
        token: str | None = None
        for page_idx in range(max_pages):
            page = await self.search_text(query, page_token=token, **kwargs)
            places = page.get("places", []) or []
            out.extend(places)
            token = page.get("nextPageToken")
            logger.info(
                "places.search_text: q=%r page=%d got=%d cum=%d next=%s",
                query, page_idx + 1, len(places), len(out), bool(token),
            )
            if not token:
                break
        return out

    async def aclose(self) -> None:
        await self._client.aclose()


def default_client() -> GooglePlacesClient:
    """Construct a client from settings."""
    target_sa = settings.gcp_target_sa or settings.gcp_places_target_sa
    if not target_sa:
        raise RuntimeError("GCP_TARGET_SA not set in .env")
    if not settings.gcp_project_id:
        raise RuntimeError("GCP_PROJECT_ID not set in .env")
    return GooglePlacesClient(
        target_sa=target_sa,
        project_id=settings.gcp_project_id,
    )
