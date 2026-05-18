"""Agent core.

LangGraph state machine that walks each lead through:

    discover → enrich → score → draft → HITL → send → track → follow-up

Modules:
- `graph`         — LangGraph state machine (to be implemented in v1).
- `llm`           — LiteLLM model router (Claude Sonnet drafter / Gemini Flash bulk).
- `recipes`       — Resolution layer: imports private playbook recipes when
                    available, falls back to `recipes_stub`.
- `recipes_stub`  — Placeholder recipes shipped with the public engine.
- `nodes/`        — One module per graph node.
"""
