"""Public, static legal-document routing for the Streamlit application."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGAL_DOCUMENTS: Mapping[str, Path] = {
    "terms": PROJECT_ROOT / "docs" / "TERMS_OF_USE.md",
    "privacy": PROJECT_ROOT / "docs" / "PRIVACY_POLICY.md",
}


def legal_document_path(slug: object) -> Path | None:
    """Resolve only a fixed public legal route, never an arbitrary path."""
    return LEGAL_DOCUMENTS.get(slug) if isinstance(slug, str) else None


def render_public_legal_page() -> bool:
    """Render an allowlisted legal document without touching private state."""
    path = legal_document_path(st.query_params.get("legal"))
    if path is None:
        return False
    st.markdown(path.read_text(encoding="utf-8"))
    st.markdown("[Back to application](?)")
    return True
