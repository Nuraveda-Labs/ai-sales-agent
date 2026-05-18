"""Idempotent pipeline + custom-property bootstrap.

Run once per portal:

    python -m sales_agent.hubspot.bootstrap_pipeline

What it does (each step is idempotent):
1. Ensures the deal pipeline named `HUBSPOT_PIPELINE_NAME` exists.
2. Ensures every stage in `stages.PIPELINE_STAGES` exists in that pipeline,
   in the right order, with the right probabilities + closed/won flags.
3. Ensures the custom contact + company + deal properties we read/write
   exist (`current_site_status`, `agent_score`, `agco_license`).

If you re-run after manually editing stages in the HubSpot UI, the
function re-aligns to the source-of-truth definition in `stages.py` —
edits in HubSpot will be overwritten on next bootstrap. That's by design:
the agent's mental model of the pipeline must match the schema.
"""

from __future__ import annotations

import logging

from sales_agent.config import settings
from sales_agent.hubspot import client
from sales_agent.hubspot.stages import PIPELINE_STAGES

logger = logging.getLogger(__name__)


# ─── Pipeline ────────────────────────────────────────────────────────────────


async def find_pipeline_by_label(label: str) -> dict | None:
    """Return the pipeline dict whose `label` matches, else None."""
    body = await client.request("GET", "/crm/v3/pipelines/deals")
    for p in body.get("results", []):
        if p.get("label") == label:
            return p
    return None


async def ensure_pipeline() -> str:
    """Ensure the configured pipeline + its stages exist. Returns pipeline id."""
    label = settings.hubspot_pipeline_name
    if not label:
        raise RuntimeError("HUBSPOT_PIPELINE_NAME not set")

    existing = await find_pipeline_by_label(label)
    if existing is None:
        logger.info("hubspot.pipelines: creating pipeline %r", label)
        body = await client.request(
            "POST", "/crm/v3/pipelines/deals",
            json={
                "label": label,
                "displayOrder": 0,
                "stages": [_stage_payload(s, idx) for idx, s in enumerate(PIPELINE_STAGES)],
            },
        )
        return body["id"]

    pipeline_id = existing["id"]
    logger.info("hubspot.pipelines: pipeline %r already exists (id=%s)", label, pipeline_id)

    # Reconcile stages — add any missing, leave existing ones alone.
    have = {s["label"]: s for s in existing.get("stages", [])}
    for idx, stage in enumerate(PIPELINE_STAGES):
        if stage[0] in have:
            continue
        logger.info("hubspot.pipelines: adding missing stage %r", stage[0])
        await client.request(
            "POST", f"/crm/v3/pipelines/deals/{pipeline_id}/stages",
            json=_stage_payload(stage, idx),
        )
    return pipeline_id


def _stage_payload(
    stage: tuple[str, float, bool, bool], display_order: int,
) -> dict:
    label, probability, is_closed, is_won = stage
    return {
        "label": label,
        "displayOrder": display_order,
        "metadata": {
            "isClosed": str(is_closed).lower(),
            "probability": str(probability),
            **({"isWon": "true"} if is_won else {}),
        },
    }


async def stage_id_by_label(pipeline_id: str, label: str) -> str | None:
    """Look up a stage's id by its label inside a known pipeline."""
    body = await client.request("GET", f"/crm/v3/pipelines/deals/{pipeline_id}")
    for s in body.get("stages", []):
        if s.get("label") == label:
            return s["id"]
    return None


# ─── Custom properties ───────────────────────────────────────────────────────

# (object_type, property_name, label, group, type, fieldType, options?)
_CUSTOM_PROPS = [
    ("contacts", "current_site_status", "Current site status",
     "contactinformation", "enumeration", "select",
     ["none", "linktree", "builder", "lightspeed", "custom"]),
    ("contacts", "agent_score", "Agent priority score",
     "contactinformation", "number", "number", None),
    ("companies", "agco_license", "AGCO licence #",
     "companyinformation", "string", "text", None),
]


async def ensure_custom_properties() -> None:
    """Create the custom properties the mapper writes if they don't exist."""
    for obj_type, name, label, group, ptype, ftype, options in _CUSTOM_PROPS:
        try:
            await client.request("GET", f"/crm/v3/properties/{obj_type}/{name}")
            logger.info("hubspot.pipelines: property %s.%s exists", obj_type, name)
            continue
        except client.HubSpotError as e:
            if e.status_code != 404:
                raise

        logger.info("hubspot.pipelines: creating property %s.%s", obj_type, name)
        payload: dict[str, object] = {
            "name": name,
            "label": label,
            "groupName": group,
            "type": ptype,
            "fieldType": ftype,
        }
        if options:
            payload["options"] = [
                {"label": o, "value": o, "displayOrder": idx}
                for idx, o in enumerate(options)
            ]
        await client.request(
            "POST", f"/crm/v3/properties/{obj_type}",
            json=payload,
        )
