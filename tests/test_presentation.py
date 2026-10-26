from __future__ import annotations

from pathlib import Path
import tomllib
from unittest.mock import patch

from tabula_rasa.presentation import DESIGN_TOKENS, global_styles, render_page_header


def test_design_tokens_match_the_shared_visual_foundation() -> None:
    assert DESIGN_TOKENS["canvas"] == "#F5F4F0"
    assert DESIGN_TOKENS["surface-primary"] == "#FFFFFF"
    assert DESIGN_TOKENS["interactive-primary"] == "#3267D6"
    assert DESIGN_TOKENS["interactive-focus"] == "#6B96ED"
    assert DESIGN_TOKENS["negative-text"] == "#B33A3A"
    assert DESIGN_TOKENS["negative-hover"] == "#942F2F"
    assert DESIGN_TOKENS["warning-text"] == "#996600"


def test_global_styles_use_stable_shell_hooks_and_accessible_states() -> None:
    css = global_styles()
    for selector in (
        '[data-testid="stSidebar"]', '[data-testid="stForm"]',
        '[data-testid="stExpander"]', '[data-testid="stAlert"]',
        '[data-testid="stMainBlockContainer"]', '.st-key-login_surface',
        '.st-key-global_footer', '.st-key-profile_readiness_status_ready_local',
        '[data-testid="InputInstructions"]', ':focus-visible',
    ):
        assert selector in css
    assert '--tr-canvas: #F5F4F0' in css
    assert '[data-testid="stTabs"] [role="tab"]' in css
    assert '[data-testid="stTabs"] [role="tab"]:focus-visible' in css
    assert 'var(--tr-positive-text);' in css
    assert 'var(--tr-warning-text) !important' in css
    assert '@media (max-width: 760px)' in css
    assert '.st-key-login_surface [data-testid="InputInstructions"]' in css


def test_streamlit_theme_matches_the_shared_tokens() -> None:
    with Path(".streamlit/config.toml").open("rb") as config_file:
        config = tomllib.load(config_file)
    theme = config["theme"]

    assert theme["primaryColor"] == DESIGN_TOKENS["interactive-primary"]
    assert theme["backgroundColor"] == DESIGN_TOKENS["canvas"]
    assert theme["secondaryBackgroundColor"] == DESIGN_TOKENS["surface-secondary"]
    assert theme["textColor"] == DESIGN_TOKENS["text-primary"]
    assert theme["borderColor"] == DESIGN_TOKENS["border-default"]
    assert config["client"]["toolbarMode"] == "viewer"


def test_render_page_header_keeps_description_optional() -> None:
    with patch("tabula_rasa.presentation.st.title") as title, patch(
        "tabula_rasa.presentation.st.caption"
    ) as caption:
        render_page_header("Transactions")
        title.assert_called_once_with("Transactions")
        caption.assert_not_called()

        render_page_header("Mileage", "Keep a dated mileage log.")
        assert title.call_count == 2
        caption.assert_called_once_with("Keep a dated mileage log.")
