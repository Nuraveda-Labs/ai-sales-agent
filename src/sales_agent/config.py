"""Settings loaded from environment.

No per-prospect config lives here — that belongs in the `sales_agent.leads`
table. This module is for runtime knobs only: API keys, the sending mailbox,
the Discord channel, the daily outreach cap, the CASL footer.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Postgres ────────────────────────────────────────────────────────────
    # Optional at import time so processes that don't touch the DB
    # (e.g. the Discord bot for non-DB slash commands) can still import
    # `sales_agent.config`. `pool.connect()` raises if it's empty when
    # someone actually tries to open a connection.
    postgres_rw_url: str = ""

    # ── GCP — shared SA + project for Places + Vertex AI ──────────────────
    gcp_project_id: str = "<your-gcp-project>"
    gcp_target_sa: str = (
        "<your-sa>@<your-project>.iam.gserviceaccount.com"
    )
    gcp_vertex_region: str = "us-central1"
    # Backward-compat alias — older code paths read gcp_places_target_sa.
    gcp_places_target_sa: str = (
        "<your-sa>@<your-project>.iam.gserviceaccount.com"
    )
    discovery_center_lat: float = 43.7615
    discovery_center_lng: float = -79.4111
    discovery_radius_m: int = 8000

    # ── Email provider switch ──────────────────────────────────────────────
    # "gmail"  → google-api-python-client via SA + domain-wide delegation
    #             (recommended for cold sales: highest Primary placement,
    #             replies thread to your Sent folder natively, looks like
    #             a real human typed it)
    # "resend" → Resend transactional API (kept for parity / future
    #             transactional flows; suboptimal for cold)
    mail_provider: str = "gmail"

    # ── Gmail Send (via SA domain-wide delegation, no key file needed) ─────
    # The SA is already configured for delegation in Workspace admin; the
    # subject is the user the SA acts AS (i.e. the from address).
    gmail_subject_user: str = "support@example.com"

    # ── Email (Resend transactional API — outbound only) ───────────────────
    # Cold outreach sends from support@example.com — already warm
    # from the  sites transactional Resend wire, so Gmail's
    # classifier puts it in Primary on landing. Display name "Tejas" gives
    # the recipient a human-named From line. Replies route back to support@
    # where the operator already reads.
    resend_api_key: str = ""
    resend_from_email: str = "support@example.com"
    resend_from_name: str = "Tejas"
    resend_reply_to: str = "support@example.com"

    # Legacy aliases — kept so older code paths that still read
    # `gmail_sender_email` resolve to the Resend from address.
    @property
    def gmail_sender_email(self) -> str:  # type: ignore[override]
        return self.resend_from_email

    @property
    def gmail_sender_name(self) -> str:  # type: ignore[override]
        return self.resend_from_name

    # ── CASL footer ────────────────────────────────────────────────────────
    casl_sender_name: str = "an open-source project (Nuraveda)"
    casl_sender_address: str = "77 Huntley St, <region>, ON"

    # ── Discord ────────────────────────────────────────────────────────────
    discord_bot_token: str = ""
    discord_guild_id: str = ""
    discord_approval_channel_id: str = ""
    discord_admin_user_ids: str = ""  # comma-separated

    # ── LLM providers ──────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    google_api_key: str = ""

    # ── Booking (Calendly / HubSpot Meetings — anything that takes a click) ─
    # Public URL, not a secret. Used in plain-text CTAs and as the primary
    # button target in the branded HTML email.
    booking_url: str = ""
    booking_duration_min: int = 30  # match the Calendly slot length

    # ── Drafter (Gemini 2.5 Pro via Vertex AI, SA-impersonation auth) ──────
    drafter_model: str = "gemini-2.5-pro"
    # Gemini 2.5 Pro burns tokens on internal reasoning before emitting,
    # so the budget covers thinking + output. 8192 leaves comfortable
    # headroom even for verbose recipes; tune down for Flash.
    drafter_max_tokens: int = 8192

    # ── HubSpot CRM mirror ────────────────────────────────────────────────
    hubspot_pat: str = ""                          # Private App token
    hubspot_pipeline_name: str = "Example Brand"
    hubspot_sync_enabled: bool = False
    hubspot_portal_id: str = ""                    # optional, informational

    # ── Server ─────────────────────────────────────────────────────────────
    agent_run_token: str = ""
    outreach_daily_cap: int = 5

    # ── Optional ───────────────────────────────────────────────────────────
    sales_agent_dry_run: bool = False
    log_level: str = "INFO"

    @property
    def admin_user_id_list(self) -> list[int]:
        return [int(x.strip()) for x in self.discord_admin_user_ids.split(",") if x.strip()]


settings = Settings()  # type: ignore[call-arg]
