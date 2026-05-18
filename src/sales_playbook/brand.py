"""Glitch Budz brand fact sheet — loaded at import time from the .md file.

The .md file is the canonical, human-edited source. This module just
exposes its contents as a Python string so the drafter can paste it
into the system context.

For non-editable installs this resolution would need package_data;
v1 deploys are editable installs of the repo so __file__ resolution
works. Promote to importlib.resources when we wheel-pack.
"""

from __future__ import annotations

from pathlib import Path

_FACT_SHEET_PATH = (
    Path(__file__).resolve().parent.parent.parent / "brand" / "glitch-budz.md"
)


def get_brand_fact_sheet() -> str:
    """Return the brand fact sheet markdown. Raises if the file is missing."""
    return _FACT_SHEET_PATH.read_text(encoding="utf-8")


# Eager-load so a missing file fails at import time, not in production.
BRAND_FACT_SHEET: str = get_brand_fact_sheet()
