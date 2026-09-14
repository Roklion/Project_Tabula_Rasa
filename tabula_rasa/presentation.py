"""Shared presentation tokens and Streamlit shell helpers."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping

import streamlit as st

from tabula_rasa.recurrence_state import (
    mixed_use_create_pending_state,
    transaction_create_pending_state,
)


DESIGN_TOKENS: Mapping[str, str] = {
    "canvas": "#F5F4F0",
    "surface-primary": "#FFFFFF",
    "surface-secondary": "#FAFAF8",
    "surface-hover": "#F2F3F4",
    "surface-selected": "#EAF0FC",
    "text-primary": "#202124",
    "text-secondary": "#62666B",
    "text-muted": "#85898E",
    "border-default": "#DDDED9",
    "border-subtle": "#E9E9E5",
    "border-strong": "#B8BAB6",
    "interactive-primary": "#3267D6",
    "interactive-hover": "#2858BC",
    "interactive-focus": "#6B96ED",
    "positive-text": "#287A4B",
    "positive-background": "#EAF5EE",
    "positive-border": "#B7DCC5",
    "negative-text": "#B33A3A",
    "negative-hover": "#942F2F",
    "negative-background": "#FBECEC",
    "negative-border": "#E8BABA",
    "warning-text": "#996600",
    "warning-background": "#FFF5D9",
    "warning-border": "#E7CE8C",
    "informational-background": "#EAF0FC",
    "informational-border": "#B8CAF1",
    "neutral-background": "#F1F2F1",
    "neutral-border": "#D5D7D4",
}

GLOBAL_FOOTER_RENDERED_KEY = "_global_footer_rendered"


def _css_variables(tokens: Mapping[str, str]) -> str:
    return "\n".join(
        f"        --tr-{name.replace('_', '-')}: {value};"
        for name, value in tokens.items()
    )


def global_styles(tokens: Mapping[str, str] = DESIGN_TOKENS) -> str:
    """Return the stable, application-wide CSS layer for the Streamlit shell."""
    return f"""
    <style>
    :root {{
{_css_variables(tokens)}
        color-scheme: light;
    }}

    html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {{
        font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
            "Segoe UI", sans-serif;
    }}

    .stApp,
    [data-testid="stAppViewContainer"] > .main {{
        background: var(--tr-canvas);
        color: var(--tr-text-primary);
    }}

    [data-testid="stMainBlockContainer"] {{
        max-width: 1440px;
        padding-top: 1.75rem;
        padding-right: clamp(1rem, 3vw, 3rem);
        padding-bottom: 3rem;
        padding-left: clamp(1rem, 3vw, 3rem);
    }}

    [data-testid="stHeader"] {{
        background: transparent;
    }}

    [data-testid="stWidgetLabel"] {{
        width: fit-content !important;
        max-width: 100%;
        justify-content: flex-start;
        gap: 0.3rem;
    }}

    [data-testid="stWidgetLabel"] > [data-testid="stMarkdownContainer"] {{
        width: fit-content !important;
        flex: 0 1 auto;
    }}

    [data-testid="stWidgetLabel"] p,
    [data-testid="stWidgetLabel"] [data-testid="stTooltipIcon"] {{
        flex: 0 0 auto;
        color: var(--tr-text-primary) !important;
    }}

    /* Keep the optional Round trip label before its checkbox. */
    .st-key-add_mileage_round_trip[data-testid="stCheckbox"] label,
    .st-key-add_mileage_round_trip [data-testid="stCheckbox"] label {{
        flex-direction: row-reverse;
        justify-content: flex-end;
    }}

    [data-testid="stTabs"] [role="tab"] {{
        color: var(--tr-text-secondary) !important;
    }}

    [data-testid="stTabs"] [role="tab"]:hover {{
        color: var(--tr-text-primary) !important;
    }}

    [data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
        color: var(--tr-text-primary) !important;
    }}

    [data-testid="stTabs"] [role="tablist"] {{
        border-bottom: 1px solid var(--tr-border-default);
        display: flex;
        align-items: flex-end;
        column-gap: 0.5rem;
        overflow-x: auto;
        scrollbar-width: thin;
    }}

    [data-testid="stTabs"] [role="tab"] {{
        flex: 0 0 auto;
        min-height: 2.5rem;
        padding: 0.55rem 0.75rem 0.5rem;
        border: 0;
        border-bottom: 2px solid transparent;
        border-radius: 4px 4px 0 0;
        background: transparent;
        white-space: nowrap;
        font-weight: 500;
    }}

    [data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
        border-bottom-color: var(--tr-interactive-primary);
        font-weight: 650;
    }}

    [data-testid="stTabs"] [role="tab"]:focus-visible {{
        outline: 2px solid var(--tr-interactive-focus);
        outline-offset: -2px;
    }}

    [data-testid="stTabs"] [role="tabpanel"] {{
        padding-top: 0.9rem;
    }}

    [data-testid="stSidebar"] {{
        background: var(--tr-surface-secondary);
        border-right: 1px solid var(--tr-border-default);
    }}

    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
        gap: 0.5rem;
    }}

    .st-key-sidebar_brand {{
        padding-bottom: 0.5rem;
        border-bottom: 1px solid var(--tr-border-subtle);
    }}

    .st-key-sidebar_business_context {{
        padding: 0.25rem 0 0.5rem;
    }}

    .st-key-sidebar_navigation [data-testid="stWidgetLabel"] {{
        margin-bottom: 0.25rem;
    }}

    .st-key-sidebar_navigation [data-testid="stWidgetLabel"] p {{
        color: var(--tr-text-muted) !important;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.025em;
    }}

    .st-key-sidebar_utility {{
        margin-top: 0.25rem;
        padding-top: 0.75rem;
        border-top: 1px solid var(--tr-border-default);
    }}

    .st-key-account_settings_navigation
    [data-testid="stBaseButton-primary"] [data-testid="stMarkdownContainer"],
    .st-key-account_settings_navigation
    [data-testid="stBaseButton-primary"] [data-testid="stMarkdownContainer"] p {{
        color: var(--tr-surface-primary) !important;
    }}

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] {{
        color: var(--tr-text-primary);
    }}

    [data-testid="stSidebar"] [role="radiogroup"] {{
        gap: 4px;
    }}

    [data-testid="stSidebar"] [role="radiogroup"] label {{
        border-radius: 6px;
        padding: 6px 8px;
        position: relative;
    }}

    /* Keep the native radio in the accessibility tree and tab order while
       presenting the navigation as a compact full-row control. */
    [data-testid="stSidebar"] [role="radiogroup"] label input[type="radio"] {{
        position: absolute;
        width: 1px;
        height: 1px;
        opacity: 0;
        margin: 0;
    }}

    /* Streamlit draws a second visual indicator beside each native radio.
       Suppress that indicator only for the navigation options. NOTE: The
       `> div > div > div` selector below is fragile because it depends on
       Streamlit's internal DOM structure and may break in future versions.
       The child layout selector also depends on that DOM and may need
       adjustment after a Streamlit upgrade. The input remains available to
       assistive technology and keyboard users. */
    [data-testid="stSidebar"] label[data-testid="stRadioOption"]
    > div > div > div:first-child:not(:has([data-testid="stMarkdownContainer"])) {{
        display: none;
    }}

    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:focus-visible) {{
        outline: 2px solid var(--tr-interactive-focus);
        outline-offset: 1px;
    }}

    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
        background: var(--tr-surface-selected);
        color: var(--tr-text-primary);
        box-shadow: inset 2px 0 0 var(--tr-interactive-primary);
    }}

    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
        color: var(--tr-text-secondary);
    }}

    h1, h2, h3 {{
        color: var(--tr-text-primary);
        letter-spacing: -0.025em;
    }}

    h1 {{
        font-size: 22px;
        font-weight: 600;
        margin-bottom: 4px;
        line-height: 1.25;
    }}

    h2, h3 {{
        font-size: 16px;
        font-weight: 600;
        line-height: 1.35;
    }}

    [data-testid="stSubheader"] {{
        margin-top: 0.75rem;
        margin-bottom: 0.35rem;
    }}

    [data-testid="stCaptionContainer"] {{
        color: var(--tr-text-secondary);
    }}

    [data-testid="stMetric"] {{
        background: var(--tr-surface-primary);
        border: 1px solid var(--tr-border-default);
        border-radius: 8px;
        box-shadow: none;
        min-height: 82px;
        padding: 12px 16px 10px;
    }}

    [data-testid="stMetricLabel"] {{
        color: var(--tr-text-secondary);
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.01em;
    }}

    [data-testid="stMetricValue"] {{
        color: var(--tr-text-primary);
        font-variant-numeric: tabular-nums;
    }}

    .st-key-profile_readiness_status_ready_local [data-testid="stMetricValue"] {{
        color: var(--tr-positive-text);
    }}

    .st-key-dashboard_metrics [data-testid="stMetricValue"] {{
        font-size: 1.25rem;
        font-weight: 600;
    }}

    .st-key-dashboard_total_balance [data-testid="stMetric"],
    .st-key-dashboard_net_month [data-testid="stMetric"] {{
        border-color: var(--tr-border-strong);
    }}

    .st-key-dashboard_total_balance [data-testid="stMetricValue"],
    .st-key-dashboard_net_month [data-testid="stMetricValue"] {{
        font-size: clamp(1.625rem, 2vw, 1.875rem);
        font-weight: 600;
    }}

    [data-testid="stDataFrame"] {{
        background: var(--tr-surface-primary);
        border: 1px solid var(--tr-border-default);
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 1px 1px rgb(32 33 36 / 3%);
    }}

    [data-testid="stDataFrame"] [role="columnheader"] {{
        background: var(--tr-surface-secondary);
        color: var(--tr-text-secondary);
        font-size: 0.76rem;
        font-weight: 650;
    }}

    [data-testid="stForm"],
    [data-testid="stExpander"],
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: var(--tr-surface-primary);
        border-color: var(--tr-border-default);
        border-radius: 8px;
    }}

    [data-testid="stForm"] {{
        padding: 0.75rem 1rem 1rem;
    }}

    .st-key-dashboard_activity,
    .st-key-dashboard_balances,
    .st-key-reports_charts,
    .st-key-reports_statement_tables,
    .st-key-data_backup_surface {{
        background: var(--tr-surface-primary);
        border: 1px solid var(--tr-border-default);
        border-radius: 8px;
        padding: 0.75rem 1rem 1rem;
    }}

    .st-key-accounts_add_form,
    .st-key-categories_add_form {{
        padding: 0.15rem 0 0.2rem;
    }}

    .st-key-transactions_add_surface,
    .st-key-transactions_ledger_surface,
    .st-key-mileage_add_surface,
    .st-key-mileage_log_surface {{
        padding-top: 0.25rem;
    }}

    .st-key-reports_period_controls {{
        padding: 0.2rem 0 0.65rem;
        border-bottom: 1px solid var(--tr-border-subtle);
    }}

    .st-key-dashboard_activity,
    .st-key-dashboard_balances {{
        min-height: 100%;
    }}

    .st-key-dashboard_activity [data-testid="stDataFrame"],
    .st-key-dashboard_balances [data-testid="stDataFrame"],
    .st-key-reports_statement_tables [data-testid="stDataFrame"] {{
        border: 0;
        border-radius: 0;
        box-shadow: none;
    }}

    .st-key-data_backup_cloud_section,
    .st-key-data_backup_recovery_section,
    .st-key-data_backup_exports_section,
    .st-key-data_backup_imports_section {{
        padding: 0.25rem 0 0.75rem;
        border-bottom: 1px solid var(--tr-border-subtle);
    }}

    .st-key-data_backup_cloud_section + .st-key-data_backup_recovery_section,
    .st-key-data_backup_recovery_section + .st-key-data_backup_exports_section,
    .st-key-data_backup_exports_section + .st-key-data_backup_imports_section {{
        margin-top: 0.5rem;
    }}

    [data-testid="stButton"] button,
    [data-testid="stFormSubmitButton"] button,
    [data-testid="stDownloadButton"] button {{
        border-radius: 6px;
        min-height: 36px;
    }}

    button:focus-visible,
    input:focus-visible,
    textarea:focus-visible,
    [role="combobox"]:focus-visible {{
        outline: 2px solid var(--tr-interactive-focus);
        outline-offset: 2px;
    }}

    [data-testid="stAlert"] {{
        border-radius: 6px;
        border-width: 1px;
    }}

    [data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"])
    [data-testid="stAlertContainer"] {{
        background: var(--tr-positive-background) !important;
        border-color: var(--tr-positive-border) !important;
    }}

    [data-testid="stAlert"]:has([data-testid="stAlertContentError"])
    [data-testid="stAlertContainer"] {{
        background: var(--tr-negative-background) !important;
        border-color: var(--tr-negative-border) !important;
    }}

    [data-testid="stAlert"]:has([data-testid="stAlertContentInfo"])
    [data-testid="stAlertContainer"] {{
        background: var(--tr-informational-background) !important;
        border-color: var(--tr-informational-border) !important;
    }}

    [data-testid="stAlert"]:has(
        [data-testid="stAlertContentWarning"]
    ) [data-testid="stAlertContainer"] {{
        background: var(--tr-warning-background) !important;
        border-color: var(--tr-warning-border) !important;
    }}

    [data-testid="stAlert"]:has([data-testid="stAlertContentWarning"])
    [data-testid="stMarkdownContainer"],
    [data-testid="stAlert"]:has([data-testid="stAlertContentWarning"])
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stAlert"]:has([data-testid="stAlertContentWarning"])
    [data-testid="stAlertDynamicIcon"] {{
        color: var(--tr-warning-text) !important;
    }}

    .st-key-destructive_category_delete [data-testid="stButton"] button,
    .st-key-destructive_asset_delete [data-testid="stButton"] button,
    .st-key-destructive_mileage_delete [data-testid="stButton"] button,
    .st-key-destructive_managed_payee_remove [data-testid="stButton"] button,
    .st-key-destructive_managed_tag_remove [data-testid="stButton"] button,
    .st-key-destructive_transaction_bulk_delete [data-testid="stFormSubmitButton"] button,
    .st-key-destructive_transaction_edit_delete [data-testid="stFormSubmitButton"] button {{
        background: var(--tr-negative-text) !important;
        border-color: var(--tr-negative-text) !important;
        color: var(--tr-surface-primary) !important;
    }}

    .st-key-destructive_category_delete [data-testid="stButton"] button:hover,
    .st-key-destructive_asset_delete [data-testid="stButton"] button:hover,
    .st-key-destructive_mileage_delete [data-testid="stButton"] button:hover,
    .st-key-destructive_managed_payee_remove [data-testid="stButton"] button:hover,
    .st-key-destructive_managed_tag_remove [data-testid="stButton"] button:hover,
    .st-key-destructive_transaction_bulk_delete [data-testid="stFormSubmitButton"] button:hover,
    .st-key-destructive_transaction_edit_delete [data-testid="stFormSubmitButton"] button:hover {{
        background: var(--tr-negative-hover) !important;
        border-color: var(--tr-negative-hover) !important;
        color: var(--tr-surface-primary) !important;
    }}

    .st-key-login_surface {{
        max-width: 480px;
        margin: 3rem auto;
        padding: 1.25rem 1.35rem 1.35rem;
        background: var(--tr-surface-primary);
        border: 1px solid var(--tr-border-default);
        border-radius: 10px;
        box-shadow: 0 8px 24px rgb(32 33 36 / 5%);
    }}

    .st-key-login_surface [data-testid="stForm"] {{
        border: 0;
        background: transparent;
        padding: 0;
    }}

    .st-key-global_footer {{
        margin-top: 2rem;
        padding-top: 0.75rem;
        border-top: 1px solid var(--tr-border-subtle);
        text-align: center;
    }}

    .st-key-global_footer [data-testid="stMarkdownContainer"] p {{
        color: var(--tr-text-muted);
        font-size: 0.8rem;
    }}

    @media (max-width: 760px) {{
        [data-testid="stMainBlockContainer"] {{
            padding-top: 1rem;
            padding-right: 0.75rem;
            padding-left: 0.75rem;
        }}

        [data-testid="stForm"] {{
            padding: 0.625rem 0.75rem 0.75rem;
        }}

        .st-key-dashboard_metrics [data-testid="stColumn"],
        .st-key-reports_summary_metrics [data-testid="stColumn"],
        .st-key-reports_statement_metrics [data-testid="stColumn"] {{
            min-width: calc(50% - 0.5rem);
            flex: 1 1 calc(50% - 0.5rem);
        }}

        .st-key-dashboard_activity,
        .st-key-dashboard_balances,
        .st-key-data_backup_surface {{
            padding-right: 0.65rem;
            padding-left: 0.65rem;
        }}

        .st-key-login_surface {{
            margin-top: 1.25rem;
            margin-bottom: 1.25rem;
        }}

        [data-testid="stTabs"] [role="tablist"] {{
            column-gap: 0.2rem;
        }}

        [data-testid="stTabs"] [role="tab"] {{
            min-height: 2.35rem;
            padding-right: 0.55rem;
            padding-left: 0.55rem;
            font-size: 0.9rem;
        }}
    }}

    /* Streamlit overlays this hint on the input row. Keep it clear of the
       password visibility toggle while preserving the Enter-to-submit cue. */
    .st-key-login_surface [data-testid="InputInstructions"] {{
        right: 42px !important;
    }}
    </style>
    """


def apply_global_styles() -> None:
    """Install the shared presentation layer before any page is rendered."""
    st.markdown(global_styles(), unsafe_allow_html=True)


def render_global_footer() -> None:
    """Render public legal links on authenticated and pre-auth surfaces."""
    st.session_state[GLOBAL_FOOTER_RENDERED_KEY] = True
    with st.container(key="global_footer"):
        st.markdown(
            "[Terms of Use](?legal=terms) | "
            "[Privacy Policy](?legal=privacy)"
        )


def reset_profile_presentation_state(
    session_state: MutableMapping[str, object],
    *,
    previous_profile_key: str | None,
    selected_profile_key: str | None,
) -> None:
    """Clear unscoped page state when the active business profile changes."""
    if previous_profile_key is None or previous_profile_key == selected_profile_key:
        return

    keys = {
        "edit_transaction_id",
        "edit_mileage_trip_id",
        "edit_account_id",
        "edit_category_id",
        "selected_asset_id",
        "write_success_notice",
        "ledger_start",
        "ledger_end",
        "mileage_start",
        "mileage_end",
        "report_start",
        "report_end",
        "balance_sheet_date",
        "transaction_bulk_scope",
        "transaction_bulk_selection_generation",
        "transaction_ledger_mode_generation",
    }
    mixed_use_keys = {
        f"mixed_use_selected_source_id_{previous_profile_key}",
        f"mixed_use_selection_scope_{previous_profile_key}",
        f"mixed_use_table_generation_{previous_profile_key}",
        f"mixed_use_edit_baseline_source_id_{previous_profile_key}",
        f"mixed_use_clear_selection_{previous_profile_key}",
        f"mixed_use_form_reset_{previous_profile_key}",
        f"mixed_use_copy_source_id_{previous_profile_key}",
        f"mixed_use_copy_snapshot_{previous_profile_key}",
        f"mixed_use_copy_new_source_id_{previous_profile_key}",
        f"mixed_use_copy_new_transaction_id_{previous_profile_key}",
        f"mixed_use_copy_generation_{previous_profile_key}",
        f"mixed_use_copy_button_{previous_profile_key}",
    }
    mixed_use_prefixes = (
        f"mixed_use_log_{previous_profile_key}_",
        f"mixed_use_copy_{previous_profile_key}_",
        f"mixed_cancel_copy_{previous_profile_key}_",
        f"mixed_use_edit_baseline_{previous_profile_key}",
        f"mixed_confirm_delete_{previous_profile_key}_",
        f"mixed_date_{previous_profile_key}_",
        f"mixed_account_{previous_profile_key}_",
        f"mixed_category_{previous_profile_key}_",
        f"mixed_payee_{previous_profile_key}_",
        f"mixed_reference_{previous_profile_key}_",
        f"mixed_description_{previous_profile_key}_",
        f"mixed_tags_{previous_profile_key}_",
        f"mixed_total_{previous_profile_key}_",
        f"mixed_percentage_{previous_profile_key}_",
        f"mixed_rationale_{previous_profile_key}_",
        f"mixed_receipts_{previous_profile_key}_",
        f"mixed_recurring_{previous_profile_key}_",
        f"mixed_recurrence_unit_{previous_profile_key}_",
        f"mixed_recurrence_interval_{previous_profile_key}_",
        f"mixed_recurrence_name_{previous_profile_key}_",
        f"mixed_recurrence_end_{previous_profile_key}_",
    )
    prefixes = (
        "add_transaction_",
        "add_mileage_",
        "add_asset_",
        "edit_asset_",
        "asset_",
        "calculate_asset_",
        "save_asset_",
        "retire_asset_",
        "delete_asset_",
        "confirm_delete_asset_",
        "edit_transaction_",
        "edit_mileage_",
        "edit_account_",
        "edit_category_",
        "confirm_delete_category_",
        "save_account_",
        "save_category_",
        "receipt_notice_",
        "receipt_candidate_",
        "receipt-unlink-notice-",
        "receipt-unlink-candidate-",
        "receipt-unlink-request-",
        "receipt-unlink-cancel-",
        "receipt-unlink-confirm-",
        "receipt-upload-",
        "quickbooks_",
        "transaction_csv_upload_",
        "reset_",
        "transaction_ledger_",
        "mileage_log_",
        "account_table_",
        "category_table_",
        "new_account_",
        "new_category_",
        "receipt-existing-",
        "prepared-live-exports:",
        "ledger_filter_",
        "ledger_search_",
        "transaction_bulk_selected_ids_",
        "transaction_ledger_mode_",
        "transaction_copy_source_",
        "transaction_copy_generation_",
        "recurring_selected_",
        "recurring_pause_",
        "recurring_resume_",
        "recurring_end_",
        "recurring_reconcile_",
        "recurring_create_",
        "recurring_edit_",
    )
    preserved_retry_prefixes = (
        "recurring_edit_pending_schedule_id_",
        "recurring_edit_pending_payload_",
        "recurring_edit_pending_configuration_revision_",
        "mixed_use_edit_pending_schedule_id_",
        "mixed_use_edit_pending_payload_",
        "mixed_use_edit_pending_configuration_revision_",
    )
    for key in list(session_state):
        if (
            key in keys
            or key in mixed_use_keys
            or (
                key.startswith(prefixes)
                and not key.startswith(preserved_retry_prefixes)
            )
            or (
                key.startswith(mixed_use_prefixes)
                and not key.startswith(preserved_retry_prefixes)
            )
        ):
            session_state.pop(key, None)


def reset_stale_recurring_pending_state(
    session_state: MutableMapping[str, object],
    *,
    profile_key: str,
    workbook_identity: str,
) -> None:
    """Discard retry state that belongs to an older workbook configuration."""
    for pending in (
        transaction_create_pending_state(profile_key),
        mixed_use_create_pending_state(profile_key),
    ):
        pending.discard_if_configuration_changed(
            session_state,
            workbook_identity,
        )


def render_page_header(title: str, description: str | None = None) -> None:
    """Render the compact title treatment shared by application pages."""
    st.title(title)
    if description:
        st.caption(description)
