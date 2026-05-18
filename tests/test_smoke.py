"""Smoke tests — package imports + recipe resolution work without a private playbook."""

from __future__ import annotations


def test_package_imports() -> None:
    import sales_agent

    assert sales_agent.__version__


def test_recipes_resolve_to_stub_when_no_private_playbook() -> None:
    """Without the private package installed, RECIPES should resolve to the stubs."""
    from sales_agent.agent import recipes_stub
    from sales_agent.agent.recipes import RECIPES

    # If ai_marketing_stack_sales_playbook is not importable in this environment,
    # the resolution layer should hand back the stubs.
    try:
        import ai_marketing_stack_sales_playbook  # noqa: F401
    except ImportError:
        assert RECIPES is recipes_stub.RECIPES


def test_stub_recipes_cover_known_site_states() -> None:
    from sales_agent.agent.recipes_stub import RECIPES

    expected = {"none", "linktree", "builder", "lightspeed", "custom"}
    assert set(RECIPES.keys()) == expected
