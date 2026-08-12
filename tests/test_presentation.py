from __future__ import annotations

from pathlib import Path
import tomllib
from unittest.mock import patch

from tabula_rasa.presentation import (
    DESIGN_TOKENS,
    global_styles,
    render_page_header,
    reset_profile_presentation_state,
)


def test_design_tokens_match_the_shared_visual_foundation() -> None:
    assert DESIGN_TOKENS["canvas"] == "#F5F4F0"
    assert DESIGN_TOKENS["surface-primary"] == "#FFFFFF"
    assert DESIGN_TOKENS["interactive-primary"] == "#3267D6"
    assert DESIGN_TOKENS["interactive-focus"] == "#6B96ED"
    assert DESIGN_TOKENS["negative-text"] == "#B33A3A"
    assert DESIGN_TOKENS["negative-hover"] == "#942F2F"


def test_global_styles_use_stable_shell_hooks_and_accessible_states() -> None:
    css = global_styles()

    for selector in (
        '[data-testid="stSidebar"]',
        '[data-testid="stMetric"]',
        '[data-testid="stDataFrame"]',
        '[data-testid="stForm"]',
        '[data-testid="stExpander"]',
        '[data-testid="stAlert"]',
        ".st-key-login_surface",
        ":focus-visible",
    ):
        assert selector in css

    assert "--tr-canvas: #F5F4F0" in css
    assert "--tr-interactive-focus: #6B96ED" in css
    assert "--tr-negative-hover: #942F2F" in css
    assert "var(--tr-negative-hover)" in css
    assert ".tr-auth-surface" not in css
    assert "[class*=" not in css


def test_streamlit_theme_matches_the_shared_tokens() -> None:
    with Path(".streamlit/config.toml").open("rb") as config_file:
        theme = tomllib.load(config_file)["theme"]

    assert theme["primaryColor"] == DESIGN_TOKENS["interactive-primary"]
    assert theme["backgroundColor"] == DESIGN_TOKENS["canvas"]
    assert theme["secondaryBackgroundColor"] == DESIGN_TOKENS["surface-secondary"]
    assert theme["textColor"] == DESIGN_TOKENS["text-primary"]
    assert theme["borderColor"] == DESIGN_TOKENS["border-default"]


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


def test_profile_switch_clears_unscoped_presentation_state() -> None:
    session_state = {
        "edit_transaction_id": "north-transaction",
        "edit_account_id": "north-account",
        "ledger_start": "north-start",
        "write_success_notice": "North saved",
        "add_transaction_amount": 42,
        "business_profile": "north",
        "profile_scoped_cache": "retain",
    }

    reset_profile_presentation_state(
        session_state,
        previous_profile_key="north",
        selected_profile_key="south",
    )

    assert "edit_transaction_id" not in session_state
    assert "edit_account_id" not in session_state
    assert "ledger_start" not in session_state
    assert "write_success_notice" not in session_state
    assert "add_transaction_amount" not in session_state
    assert session_state["profile_scoped_cache"] == "retain"


def test_initial_profile_selection_preserves_existing_session_state() -> None:
    session_state = {
        "authenticated": True,
        "preinitialized_value": "retain",
    }

    reset_profile_presentation_state(
        session_state,
        previous_profile_key=None,
        selected_profile_key="north",
    )

    assert session_state == {
        "authenticated": True,
        "preinitialized_value": "retain",
    }
