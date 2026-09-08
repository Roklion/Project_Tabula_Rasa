"""Shared helpers used only by explicit legacy payee migration tools."""

from __future__ import annotations

from uuid import NAMESPACE_URL
from uuid import uuid5

from tabula_rasa.storage import normalize_payee_name


def legacy_payee_id(name: str) -> str:
    """Return the deterministic ID used when converting legacy payee text."""
    return str(uuid5(NAMESPACE_URL, f"tabula-rasa:payee:{normalize_payee_name(name)}"))
