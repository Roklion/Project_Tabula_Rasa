"""Resolve isolated business-profile settings from Streamlit secrets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Mapping


class BusinessProfileConfigurationError(ValueError):
    """Raised when business-profile secrets are missing or malformed."""


@dataclass(frozen=True)
class BusinessProfile:
    key: str
    name: str
    secrets: Mapping[str, Any]


def load_business_profiles(secrets: Mapping[str, Any]) -> list[BusinessProfile]:
    """Return configured business profiles."""
    configured = secrets.get("business_profiles")
    if configured is None:
        raise BusinessProfileConfigurationError(
            "No business profiles are configured."
        )

    try:
        items = list(configured.items())
    except AttributeError as exc:
        raise BusinessProfileConfigurationError(
            "business_profiles must be a table of named profiles."
        ) from exc
    if not items:
        raise BusinessProfileConfigurationError(
            "At least one business profile must be configured."
        )

    profiles: list[BusinessProfile] = []
    names: set[str] = set()
    for raw_key, raw_settings in items:
        key = str(raw_key).strip()
        if not key or not isinstance(raw_settings, Mapping):
            raise BusinessProfileConfigurationError(
                "Every business profile must have a non-empty key and settings table."
            )
        if "spreadsheet_id" not in raw_settings or "gcp_service_account" not in raw_settings:
            raise BusinessProfileConfigurationError(
                f"Business profile '{key}' needs spreadsheet_id and gcp_service_account."
            )
        name = str(raw_settings.get("name", key)).strip()
        if not name:
            raise BusinessProfileConfigurationError(
                f"Business profile '{key}' needs a non-empty name."
            )
        folded_name = name.casefold()
        if folded_name in names:
            raise BusinessProfileConfigurationError(
                "Business profile display names must be unique."
            )
        names.add(folded_name)
        profiles.append(BusinessProfile(key=key, name=name, secrets=raw_settings))
    return profiles


def select_profile_secrets(
    secrets: Mapping[str, Any], profile_key: str | None
) -> Mapping[str, Any]:
    """Return Google settings for a requested profile key."""
    profiles = load_business_profiles(secrets)
    selected = profile_key or profiles[0].key
    for profile in profiles:
        if profile.key == selected:
            return profile.secrets
    raise BusinessProfileConfigurationError(
        f"Unknown business profile: {selected}"
    )


def configured_spreadsheet_ids(
    profiles: Iterable[BusinessProfile],
) -> frozenset[str]:
    """Return every non-empty live workbook ID in configured profiles."""
    return frozenset(
        spreadsheet_id
        for profile in profiles
        if (
            spreadsheet_id := str(
                profile.secrets.get("spreadsheet_id") or ""
            ).strip()
        )
    )
