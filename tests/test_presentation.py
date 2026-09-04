from __future__ import annotations

from pathlib import Path
import re
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
        '[data-testid="stMainBlockContainer"]',
        ".st-key-login_surface",
        ".st-key-global_footer",
        ".st-key-add_mileage_round_trip",
        '[data-testid="InputInstructions"]',
        ":focus-visible",
    ):
        assert selector in css

    assert "--tr-canvas: #F5F4F0" in css
    assert "--tr-interactive-focus: #6B96ED" in css
    assert "--tr-negative-hover: #942F2F" in css
    assert "var(--tr-negative-hover)" in css
    assert '[data-testid="stAlertContentWarning"]' in css
    for selector in (
        '.st-key-destructive_category_delete [data-testid="stButton"]',
        '.st-key-destructive_mileage_delete [data-testid="stButton"]',
        '.st-key-destructive_managed_payee_remove [data-testid="stButton"]',
        '.st-key-destructive_managed_tag_remove [data-testid="stButton"]',
        '.st-key-destructive_transaction_bulk_delete'
        ' [data-testid="stFormSubmitButton"]',
        '.st-key-destructive_transaction_edit_delete'
        ' [data-testid="stFormSubmitButton"]',
    ):
        assert selector in css
    assert ':has([data-testid="stIconMaterial"])' not in css
    assert '[data-testid="stWidgetLabel"] p' in css
    assert (
        '.st-key-add_mileage_round_trip[data-testid="stCheckbox"] label' in css
    )
    assert "flex-direction: row-reverse" in css
    assert '[data-testid="stTabs"] [role="tab"]' in css
    assert '[data-testid="stMainBlockContainer"]' in css
    assert '.st-key-dashboard_total_balance' in css
    assert '.st-key-dashboard_activity' in css
    assert '.st-key-sidebar_utility' in css
    assert '.st-key-profile_readiness_status_ready_local' in css
    assert (
        '.st-key-profile_readiness_status_ready_local [data-testid="stMetricValue"]'
        in css
    )
    assert 'var(--tr-positive-text);' in css
    workspace_label_selector = (
        '.st-key-sidebar_navigation [data-testid="stWidgetLabel"] p'
    )
    workspace_label_start = css.index(workspace_label_selector)
    workspace_label_rule = css[
        workspace_label_start : css.index("}", workspace_label_start)
    ]
    assert "color: var(--tr-text-muted) !important;" in workspace_label_rule
    assert "font-size: 0.75rem;" in workspace_label_rule
    assert "font-weight: 600;" in workspace_label_rule
    assert "letter-spacing: 0.025em;" in workspace_label_rule
    settings_label_selector = re.compile(
        r'\.st-key-account_settings_navigation\s+'
        r'\[data-testid="stBaseButton-primary"\]\s+'
        r'\[data-testid="stMarkdownContainer"\] p'
    )
    settings_label_match = settings_label_selector.search(css)
    assert settings_label_match is not None
    settings_label_rule_start = settings_label_match.start()
    settings_label_rule = css[
        settings_label_rule_start : css.index("}", settings_label_rule_start)
    ]
    assert "color: var(--tr-surface-primary) !important;" in settings_label_rule
    assert 'label input[type="radio"]' in css
    assert 'label:has(input:focus-visible)' in css
    assert 'label[data-testid="stRadioOption"]' in css
    assert 'div:first-child:not(:has([data-testid="stMarkdownContainer"]))' in css
    assert '.st-key-login_surface [data-testid="stForm"]' in css
    assert '.st-key-data_backup_cloud_section' in css
    assert '.st-key-reports_statement_tables' in css
    assert '[data-testid="stTabs"] [role="tabpanel"]' in css
    assert '.st-key-reports_period_controls' in css
    tablist_start = css.index('[data-testid="stTabs"] [role="tablist"]')
    tab_selector = '[data-testid="stTabs"] [role="tab"] {'
    tab_rule_start = css.index(tab_selector, css.index(tab_selector) + 1)
    tab_rule = css[tab_rule_start : css.index("}", tab_rule_start)]
    selected_selector = (
        '[data-testid="stTabs"] [role="tab"][aria-selected="true"]'
    )
    selected_rule_start = css.index(
        selected_selector, css.index(selected_selector) + 1
    )
    selected_rule = css[
        selected_rule_start : css.index("}", selected_rule_start)
    ]
    assert "column-gap: 0.5rem;" in css[
        tablist_start : css.index("}", tablist_start)
    ]
    assert "padding: 0.55rem 0.75rem 0.5rem;" in tab_rule
    assert "border-bottom: 2px solid transparent;" in tab_rule
    assert "border-bottom-color: var(--tr-interactive-primary);" in selected_rule
    assert "font-weight: 650;" in selected_rule
    assert '[data-testid="stTabs"] [role="tab"]:focus-visible' in css
    assert "column-gap: 0.2rem;" in css[css.index("@media (max-width: 760px)") :]
    form_selector = '[data-testid="stForm"] {'
    form_rule_start = css.index(form_selector)
    form_rule = css[form_rule_start : css.index("}", form_rule_start)]
    assert "padding: 0.75rem 1rem 1rem;" in form_rule
    mobile_css = css[css.index("@media (max-width: 760px)") :]
    mobile_form_start = mobile_css.index(form_selector)
    mobile_form_rule = mobile_css[
        mobile_form_start : mobile_css.index("}", mobile_form_start)
    ]
    assert "padding: 0.625rem 0.75rem 0.75rem;" in mobile_form_rule
    supporting = '.st-key-dashboard_metrics [data-testid="stMetricValue"]'
    primary = '.st-key-dashboard_total_balance [data-testid="stMetricValue"]'
    assert supporting in css
    assert primary in css
    supporting_rule = css[css.index(supporting) : css.index("}", css.index(supporting))]
    primary_rule = css[css.index(primary) : css.index("}", css.index(primary))]
    assert "font-size: 1.25rem;" in supporting_rule
    assert "font-weight: 600;" in supporting_rule
    assert "font-size: clamp(1.625rem, 2vw, 1.875rem);" in primary_rule
    assert "font-size: 1.25rem;" not in primary_rule
    radio_rule_start = css.index('label[data-testid="stRadioOption"]')
    radio_rule = css[radio_rule_start : css.index("}", radio_rule_start)]
    assert "display: none;" in radio_rule
    assert "input[type=\"radio\"]" not in radio_rule
    assert '[data-testid="stTabs"] [role="tab"]:hover' in css
    assert (
        '.st-key-login_surface [data-testid="InputInstructions"] {\n'
        '        right: 42px !important;'
    ) in css
    assert '[aria-selected="true"]' in css
    assert "var(--tr-warning-background) !important" in css
    assert "var(--tr-warning-text) !important" in css
    assert "var(--tr-negative-text) !important" in css
    assert ".tr-auth-surface" not in css
    assert "[class*=" not in css


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
        "transaction_bulk_selected_ids_north": ("north-transaction",),
        "transaction_bulk_scope": ("north",),
        "transaction_bulk_selection_generation": 4,
        "transaction_ledger_mode_north": "Bulk",
        "mixed_use_selected_source_id_north": "north-source",
        "mixed_use_selection_scope_north": ("north", ("north-source",), 1, ()),
        "mixed_use_table_generation_north": 2,
        "mixed_use_edit_baseline_north": {"id": "north-source"},
        "mixed_use_pending_source_id_north": "pending-source",
        "mixed_use_pending_transaction_id_north": "pending-transaction",
        "mixed_date_north_north-source": "stale-date",
        "mixed_total_north_north-source": "stale-total",
        "mixed_confirm_delete_north_north-source": True,
        "mixed_use_receipt_recovery_north": {"pending": True},
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
    assert "transaction_bulk_selected_ids_north" not in session_state
    assert "transaction_bulk_scope" not in session_state
    assert "transaction_bulk_selection_generation" not in session_state
    assert "transaction_ledger_mode_north" not in session_state
    assert "mixed_use_selected_source_id_north" not in session_state
    assert "mixed_use_selection_scope_north" not in session_state
    assert "mixed_use_table_generation_north" not in session_state
    assert "mixed_use_edit_baseline_north" not in session_state
    assert session_state["mixed_use_pending_source_id_north"] == "pending-source"
    assert session_state["mixed_use_pending_transaction_id_north"] == "pending-transaction"
    assert "mixed_date_north_north-source" not in session_state
    assert "mixed_total_north_north-source" not in session_state
    assert "mixed_confirm_delete_north_north-source" not in session_state
    assert session_state["mixed_use_receipt_recovery_north"] == {"pending": True}
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
