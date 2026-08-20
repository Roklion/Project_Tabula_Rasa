"""Shared presentation tokens and Streamlit shell helpers."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping

import streamlit as st


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

    [data-testid="stTabs"] [role="tab"] {{
        color: var(--tr-text-secondary) !important;
    }}

    [data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
        color: var(--tr-text-primary) !important;
    }}

    [data-testid="stSidebar"] {{
        background: var(--tr-surface-secondary);
        border-right: 1px solid var(--tr-border-default);
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
    }}

    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
        background: var(--tr-surface-selected);
        color: var(--tr-text-primary);
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
    }}

    h2, h3 {{
        font-size: 16px;
        font-weight: 600;
    }}

    [data-testid="stCaptionContainer"] {{
        color: var(--tr-text-secondary);
    }}

    [data-testid="stMetric"] {{
        background: var(--tr-surface-primary);
        border: 1px solid var(--tr-border-default);
        border-radius: 8px;
        box-shadow: none;
        padding: 12px 16px;
    }}

    [data-testid="stDataFrame"] {{
        background: var(--tr-surface-primary);
        border: 1px solid var(--tr-border-default);
        border-radius: 8px;
        overflow: hidden;
    }}

    [data-testid="stForm"],
    [data-testid="stExpander"],
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: var(--tr-surface-primary);
        border-color: var(--tr-border-default);
        border-radius: 8px;
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

    [data-testid="stFormSubmitButton"]:has(
        [data-testid="stIconMaterial"]
    ) button {{
        background: var(--tr-negative-text) !important;
        border-color: var(--tr-negative-text) !important;
        color: var(--tr-surface-primary) !important;
    }}

    [data-testid="stFormSubmitButton"]:has(
        [data-testid="stIconMaterial"]
    ) button:hover {{
        background: var(--tr-negative-hover) !important;
        border-color: var(--tr-negative-hover) !important;
        color: var(--tr-surface-primary) !important;
    }}

    .st-key-login_surface {{
        max-width: 480px;
        margin: 24px auto;
    }}
    </style>
    """


def apply_global_styles() -> None:
    """Install the shared presentation layer before any page is rendered."""
    st.markdown(global_styles(), unsafe_allow_html=True)


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
        "write_success_notice",
        "ledger_start",
        "ledger_end",
        "mileage_start",
        "mileage_end",
        "report_start",
        "report_end",
        "balance_sheet_date",
    }
    prefixes = (
        "add_transaction_",
        "add_mileage_",
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
    )
    for key in list(session_state):
        if key in keys or key.startswith(prefixes):
            session_state.pop(key, None)


def render_page_header(title: str, description: str | None = None) -> None:
    """Render the compact title treatment shared by application pages."""
    st.title(title)
    if description:
        st.caption(description)
