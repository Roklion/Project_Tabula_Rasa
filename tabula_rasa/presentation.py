"""Shared presentation tokens and Streamlit shell helpers."""

from __future__ import annotations

from collections.abc import Mapping

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
    with st.container(key="global_footer"):
        st.markdown(
            "[Terms of Use](?legal=terms) | "
            "[Privacy Policy](?legal=privacy)"
        )


def render_page_header(title: str, description: str | None = None) -> None:
    """Render the compact title treatment shared by application pages."""
    st.title(title)
    if description:
        st.caption(description)
