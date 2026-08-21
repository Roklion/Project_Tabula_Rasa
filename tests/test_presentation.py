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
    assert DESIGN_TOKENS["warning-text"] == "#996600"


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
    assert '[data-testid="stAlertContentWarning"]' in css
    assert '[data-testid="stFormSubmitButton"]:has(' in css
    assert '[data-testid="stWidgetLabel"] p' in css
    assert '[data-testid="stTabs"] [role="tab"]' in css
    assert '[data-testid="stTabs"] [role="tab"]:hover' in css
    assert '[aria-selected="true"]' in css
    assert "var(--tr-warning-background) !important" in css
    assert "var(--tr-warning-text) !important" in css
    assert "var(--tr-negative-text) !important" in css
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
        "edit_account_name_shared": "North account",
        "edit_category_kind_shared": "Expense",
        "edit_transaction_amount_north_north-transaction": 42.0,
        "edit_transaction_confirm_delete_north_north-transaction": True,
        "edit_mileage_trip_notes_north_north-trip": "North notes",
        "edit_mileage_trip_confirm_delete_north_north-trip": True,
        "confirm_delete_category_shared": True,
        "save_account_shared": True,
        "save_category_shared": True,
        "transaction_ledger_north_0": "selected-rows",
        "mileage_log_north_0": "selected-rows",
        "account_table_north_0": "selected-rows",
        "category_table_north_0": "selected-rows",
        "transaction_csv_upload_north": "private-upload",
        "receipt-unlink-notice-north-transaction": "Receipt removed",
        "receipt-unlink-candidate-north-transaction": "receipt-123",
        "new_account_name_north": "North Bank",
        "new_category_name_north": "North Category",
        "receipt-existing-select-north-transaction": "receipt-abc",
        "prepared-live-exports:north:1:0": b"export-bytes",
        "ledger_filter_type_north": "Expense",
        "ledger_filter_accounts_north": ["Checking"],
        "ledger_search_north_1": "vendor",
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
    assert "edit_account_name_shared" not in session_state
    assert "edit_category_kind_shared" not in session_state
    assert "edit_transaction_amount_north_north-transaction" not in session_state
    assert "edit_transaction_confirm_delete_north_north-transaction" not in session_state
    assert "edit_mileage_trip_notes_north_north-trip" not in session_state
    assert "edit_mileage_trip_confirm_delete_north_north-trip" not in session_state
    assert "confirm_delete_category_shared" not in session_state
    assert "save_account_shared" not in session_state
    assert "save_category_shared" not in session_state
    assert "transaction_ledger_north_0" not in session_state
    assert "mileage_log_north_0" not in session_state
    assert "account_table_north_0" not in session_state
    assert "category_table_north_0" not in session_state
    assert "transaction_csv_upload_north" not in session_state
    assert "receipt-unlink-notice-north-transaction" not in session_state
    assert "receipt-unlink-candidate-north-transaction" not in session_state
    assert "new_account_name_north" not in session_state
    assert "new_category_name_north" not in session_state
    assert "receipt-existing-select-north-transaction" not in session_state
    assert "prepared-live-exports:north:1:0" not in session_state
    assert "ledger_filter_type_north" not in session_state
    assert "ledger_filter_accounts_north" not in session_state
    assert "ledger_search_north_1" not in session_state
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
