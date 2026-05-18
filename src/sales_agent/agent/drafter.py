"""Cold-email drafter — deterministic template renderer (default) +
optional Gemini 2.5 Pro mode for future creative drafts.

Why template-only by default:
The recipes in `ai_marketing_stack_sales_playbook.recipes` are FULL TEMPLATES
with `{shop_name}` placeholders. The drafter's job is substitution +
subject selection — both deterministic operations. When we routed
this through Gemini, the model occasionally drifted (rewrote the
CTA, dropped lines, summarized the body). Drift is the enemy of
predictable cold outreach.

So `Drafter.draft()` runs a pure substitution by default:
  - Subject: hash(lead_id) % len(variants) — deterministic A/B.
  - Body:    recipe.opener + '\\n\\n' + recipe.body, with shop_name
             substituted everywhere via str.format.

The Gemini path is preserved as `Drafter.draft_via_llm()` for future
use cases that genuinely benefit from creative variation: post-reply
drafts where prior_context informs the response, or per-shop mock-up
captioning.

Auth (LLM mode): same SA-impersonation pattern as the Places worker.
ADC picks up the box's attached Compute SA, which impersonates
`glitch-vertex-ai@…` so all Vertex calls are attributed to the
operations SA.

Output: `DraftResult` with subject_variant, subject, body, and token
telemetry (zero for template mode).

The CASL footer is appended by the sender at send time — never by the
drafter — so footer + sender identity stay infra-controlled.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from sales_agent.agent.recipes import RECIPES
from sales_agent.config import settings
from sales_agent.db.models import Lead

logger = logging.getLogger(__name__)

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


@dataclass
class DraftResult:
    subject_variant: str
    subject: str
    body: str
    model: str
    input_tokens: int
    output_tokens: int
    # Hook-aware recipe key like "brochure:chains_have" so per-hook lift
    # can be measured. Plain platform key still works as a fallback prefix.
    recipe_key: str = ""


# JSON schema enforced via Vertex's response_schema. No more prose-coaxing
# the model into well-formed JSON; the SDK guarantees the shape.
_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject_variant": {"type": "string"},
        "subject":         {"type": "string"},
        "body":            {"type": "string"},
    },
    "required": ["subject_variant", "subject", "body"],
}


# ─── Prompt construction ─────────────────────────────────────────────────────


def render_user_prompt(lead: Lead, *, prior_context: str = "") -> str:
    platform = lead.pos_platform or lead.current_site_status or "custom"
    recipe = RECIPES.get(platform) or RECIPES.get("custom")
    if recipe is None:
        raise RuntimeError(
            "Recipe library missing 'custom' fallback — playbook misconfigured"
        )

    parts: list[str] = [
        "## Brand fact sheet — immutable, do not contradict",
        get_brand_fact_sheet(),
        "",
        "## Lead facts",
        f"- shop_name: {lead.business_name}",
        f"- neighbourhood: {lead.city or '<region>'}",
        f"- province: {lead.province}",
        f"- pos_platform: {platform}",
        f"- score: {lead.score}/100",
        f"- to_email: {lead.contact_email or '(unknown)'}",
        f"- website: {lead.website_url or '(none)'}",
        "",
        f"## Recipe (selected by pos_platform={platform})",
        f"- subject variants (pick ONE, do not invent): {list(recipe.subjects)}",
        f"- opener template: {recipe.opener!r}",
        "- body template (use as-is, only substitute {shop_name}):",
        recipe.body,
    ]

    if prior_context:
        parts += [
            "",
            "## Prior context (use to inform tone, do NOT paste verbatim)",
            prior_context,
        ]

    parts += [
        "",
        "## Output rules",
        "- pick `subject_variant` from the variants list above; do not invent a new subject",
        "- substitute {shop_name} with the actual shop name in the rendered subject + body",
        "- if the opener template is empty, omit the opener line entirely",
        "- keep the body ≤ 120 words",
        "- do not add prices, claims, or URLs that are not in the brand fact sheet or recipe template",
        "- the sender will append the CASL footer; do NOT include it",
    ]
    return "\n".join(parts)


# ─── Drafter ─────────────────────────────────────────────────────────────────


def _build_vertex_client() -> genai.Client:
    """Construct a google-genai Client wired for Vertex with SA impersonation."""
    source, _ = google_default(scopes=[CLOUD_PLATFORM_SCOPE])
    imp = ImpersonatedCredentials(
        source_credentials=source,
        target_principal=settings.gcp_target_sa,
        target_scopes=[CLOUD_PLATFORM_SCOPE],
        lifetime=3600,
    )
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project_id,
        location=settings.gcp_vertex_region,
        credentials=imp,
    )


def _clean_host(url: str | None) -> str:
    """Bare hostname for personalization: drop scheme + www. + path/query.

    Hunny Pot's stored website_url was the full deep-link
    `thehunnypot.com/4936-yonge-street-north-york-<industry>-menu` —
    we want just `thehunnypot.com` in cold-email prose.

    Returns empty string when the lead has no URL.
    """
    if not url:
        return ""
    s = url.strip()
    for scheme in ("https://", "http://"):
        if s.startswith(scheme):
            s = s[len(scheme):]
    s = s.removeprefix("www.")
    # Drop path / query / fragment — keep only the hostname.
    for sep in ("/", "?", "#"):
        if sep in s:
            s = s.split(sep, 1)[0]
    return s


def _hash_pick(lead: Lead, options: tuple, *, salt: str = "") -> int:
    """Stable hash → index. Same lead + salt always returns the same index,
    so per-lead Hook + subject choice is stable across re-drafts and we
    can attribute open / reply rate per (hook, subject) cleanly."""
    if not options:
        raise RuntimeError("hash_pick called with empty options tuple")
    seed = f"{lead.id}:{salt}".encode()
    return int(hashlib.md5(seed).hexdigest(), 16) % len(options)


def _resolve_recipe(lead: Lead):
    platform = lead.pos_platform or lead.current_site_status or "custom"
    recipe = RECIPES.get(platform) or RECIPES.get("custom")
    if recipe is None:
        raise RuntimeError("Recipe library missing 'custom' fallback")
    return platform, recipe


def render_template(lead: Lead) -> DraftResult:
    """Pure-substitution renderer. No LLM, no network, deterministic.

    For each lead:
        1. Resolve recipe by `pos_platform`.
        2. Hash-pick a Hook from recipe.hooks (different lead → different
           hook → natural cohort variety; same lead → same hook on retry).
        3. Hash-pick a subject variant from hook.subjects (separate salt
           so subject A/B isn't perfectly correlated with hook choice).
        4. Substitute `{shop_name}` in subject + opener + body.
    """
    platform, recipe = _resolve_recipe(lead)
    if not recipe.hooks:
        raise RuntimeError(f"Recipe {platform!r} has no hooks defined")

    hook = recipe.hooks[_hash_pick(lead, recipe.hooks, salt="hook")]
    subject_template = hook.subjects[_hash_pick(lead, hook.subjects, salt="subj")]

    # Personalization slots available to recipe templates:
    # {shop_name}    — always set; falls back to "your shop" if missing
    # {website_url}  — the bare hostname (no scheme, no trailing slash);
    #                  empty string when the lead has no website (drafter
    #                  treats this as a render-time signal that the
    #                  pos_platform=none recipe was selected, where the
    #                  hook body doesn't reference the URL)
    # {city}         — neighbourhood / city; falls back to "your area"
    fmt_args = {
        "shop_name": lead.business_name or "your shop",
        "website_url": _clean_host(lead.website_url),
        "city": lead.city or "your area",
    }
    subject = subject_template.format(**fmt_args)

    parts: list[str] = []
    if hook.opener:
        parts.append(hook.opener.format(**fmt_args))
    parts.append(hook.body.format(**fmt_args))
    body = "\n\n".join(parts)

    # Track the hook in the recipe_key field so /recipes lift can attribute
    # open + reply rates per hook, not just per platform.
    recipe_key_with_hook = f"{platform}:{hook.name}"

    return DraftResult(
        subject_variant=subject_template,
        subject=subject,
        body=body,
        model="template",
        input_tokens=0,
        output_tokens=0,
        recipe_key=recipe_key_with_hook,
    )


class Drafter:
    """Default drafter — pure template substitution, no LLM call.

    For future creative drafts (post-reply follow-ups, mock-up captions,
    operator-edit re-rolls) use Drafter(use_llm=True) which routes
    through Gemini 2.5 Pro on Vertex.
    """

    def __init__(
        self,
        *,
        use_llm: bool = False,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.use_llm = use_llm
        self.model = model or settings.drafter_model
        self.max_tokens = max_tokens or settings.drafter_max_tokens
        self._client = None  # built lazily on first LLM call

    async def draft(
        self, lead: Lead, *, prior_context: str = "",
    ) -> DraftResult:
        if not self.use_llm:
            return render_template(lead)
        return await self._draft_via_llm(lead, prior_context=prior_context)

    async def _draft_via_llm(
        self, lead: Lead, *, prior_context: str = "",
    ) -> DraftResult:
        """LLM-backed creative path. Used for follow-ups + edge cases
        where genuine variation matters more than fidelity to a template."""
        # Lazy imports keep template-only deploys lean (no google-genai
        # required if use_llm stays False).
        from google import genai
        from google.genai import types as genai_types

        from sales_agent.agent.brand import get_brand_fact_sheet
        from sales_agent.agent.prompts import get_system_prompt

        if self._client is None:
            self._client = _build_vertex_client()

        user_prompt = render_user_prompt(lead, prior_context=prior_context)
        system = get_system_prompt()

        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self.max_tokens,
            response_mime_type="application/json",
            response_schema=_DRAFT_SCHEMA,
            temperature=0.3,
        )

        resp = await self._client.aio.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=config,
        )

        text = (resp.text or "").strip()
        if not text:
            raise RuntimeError(
                f"Drafter: empty response from {self.model}; "
                f"finish_reason={getattr(resp.candidates[0], 'finish_reason', '?') if resp.candidates else '?'}"
            )

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Drafter: model returned non-JSON output despite schema:\n{text[:500]}"
            ) from e

        for required in ("subject_variant", "subject", "body"):
            if required not in parsed:
                raise RuntimeError(
                    f"Drafter: missing field {required!r} in model output: {parsed!r}"
                )

        usage = resp.usage_metadata
        return DraftResult(
            subject_variant=str(parsed["subject_variant"]),
            subject=str(parsed["subject"]),
            body=str(parsed["body"]),
            model=self.model,
            input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
        )
