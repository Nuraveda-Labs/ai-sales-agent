"""FastAPI server.

Exposes:
- GET  /healthz          — public liveness probe
- POST /agent/run        — bearer-token-gated; kicks the LangGraph state machine
                           (used by Cloud Scheduler for the daily discovery + draft sweep)

The Discord bot runs as a separate long-lived process (see sales_agent.discord.bot)
since gateway connections don't fit a scale-to-zero web service.
"""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, status

from sales_agent.config import settings

app = FastAPI(title="AI Marketing Stack AI Sales Agent")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agent/run")
async def agent_run(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not settings.agent_run_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "agent run endpoint disabled")
    if authorization != f"Bearer {settings.agent_run_token}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad bearer token")

    # TODO(v1): kick LangGraph state machine. Stub for now so the surface compiles.
    return {"status": "queued"}
