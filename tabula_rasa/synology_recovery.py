"""Validate optional per-profile Synology recovery-copy configuration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SYNC_DIRECTION = "Download remote changes only"
DESTINATION_DELETIONS = "Disabled"
MAX_FIELD_LENGTH = 500
REQUIRED_FIELDS = {
    "destination_path",
    "schedule",
    "retention_policy",
}


class SynologyRecoveryConfigurationError(ValueError):
    """Raised when Synology recovery-copy metadata is incomplete or unsafe."""


def _required_text(raw: Mapping[str, Any], field: str, label: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str):
        raise SynologyRecoveryConfigurationError(f"{label} is required.")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_FIELD_LENGTH
        or any(ord(character) < 32 for character in normalized)
    ):
        raise SynologyRecoveryConfigurationError(
            f"{label} must contain between 1 and {MAX_FIELD_LENGTH} safe characters."
        )
    return normalized


def validate_synology_recovery_settings(value: object) -> dict[str, str]:
    """Return normalized, non-secret recovery-copy metadata."""
    if not isinstance(value, Mapping):
        raise SynologyRecoveryConfigurationError(
            "Synology recovery settings are invalid."
        )
    raw = {str(key): item for key, item in value.items()}
    if set(raw) != REQUIRED_FIELDS:
        raise SynologyRecoveryConfigurationError(
            "Synology recovery settings contain unsupported fields."
        )
    destination = _required_text(raw, "destination_path", "NAS destination path")
    if not destination.startswith("/"):
        raise SynologyRecoveryConfigurationError(
            "NAS destination path must be an absolute DSM path, such as "
            "/volume1/Backups/TabulaRasa/business."
        )
    return {
        "destination_path": destination,
        "schedule": _required_text(raw, "schedule", "Cloud Sync schedule"),
        "retention_policy": _required_text(
            raw,
            "retention_policy",
            "NAS retention policy",
        ),
    }
