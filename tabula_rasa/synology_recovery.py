"""Validate optional per-profile Synology recovery-copy configuration."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping
from typing import Any


SYNC_DIRECTION = "Download remote changes only"
DESTINATION_DELETIONS = "Disabled"
PROFILE_ROOT_LAYOUT = "profile-root"
DEFAULT_BASE_PATH = "/volume1/Tabula_Rosa_Backups"
DEFAULT_SCHEDULE = "Continuous"
DEFAULT_RETENTION_POLICY = (
    "Retain all synchronized generations until quarterly manual review."
)
MAX_FIELD_LENGTH = 500
REQUIRED_FIELDS = {
    "layout",
    "destination_path",
    "schedule",
    "retention_policy",
}
DEFAULT_FIELDS = {"base_path", "schedule", "retention_policy"}
DSM_VOLUME_PATTERN = re.compile(r"volume(?:\d+|usb\d+|sata\d+)", re.IGNORECASE)


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


def _absolute_dsm_path(value: str, label: str) -> str:
    if not value.startswith("/"):
        raise SynologyRecoveryConfigurationError(
            f"{label} must be an absolute DSM path, such as "
            "/volume1/Tabula_Rosa_Backups."
        )
    normalized = posixpath.normpath(value)
    segments = normalized.strip("/").split("/")
    if len(segments) < 2 or not DSM_VOLUME_PATTERN.fullmatch(segments[0]):
        raise SynologyRecoveryConfigurationError(
            f"{label} must include a Synology volume and shared folder, such as "
            "/volume1/Tabula_Rosa_Backups."
        )
    return "/" + normalized.lstrip("/")


def validate_synology_recovery_settings(value: object) -> dict[str, str]:
    """Return normalized profile-root Synology recovery metadata."""
    if not isinstance(value, Mapping):
        raise SynologyRecoveryConfigurationError(
            "Synology recovery settings are invalid."
        )
    raw = {str(key): item for key, item in value.items()}
    fields = set(raw)
    if fields == REQUIRED_FIELDS - {"layout"}:
        raise SynologyRecoveryConfigurationError(
            "Synology recovery settings use the retired three-field schema; "
            f"include layout='{PROFILE_ROOT_LAYOUT}'."
        )
    if fields != REQUIRED_FIELDS:
        raise SynologyRecoveryConfigurationError(
            "Synology recovery settings contain unsupported fields."
        )
    if raw["layout"] != PROFILE_ROOT_LAYOUT:
        raise SynologyRecoveryConfigurationError(
            f"Synology recovery layout must be '{PROFILE_ROOT_LAYOUT}'."
        )
    normalized = {
        "destination_path": _absolute_dsm_path(
            _required_text(raw, "destination_path", "NAS destination path"),
            "NAS destination path",
        ),
        "schedule": _required_text(raw, "schedule", "Cloud Sync schedule"),
        "retention_policy": _required_text(
            raw,
            "retention_policy",
            "NAS retention policy",
        ),
    }
    return {"layout": PROFILE_ROOT_LAYOUT, **normalized}


def resolve_synology_recovery_defaults(
    value: object,
    profile_key: str,
) -> dict[str, str]:
    """Resolve reviewable root-sync defaults for one isolated profile."""
    if value is None:
        raw: dict[str, Any] = {}
    elif isinstance(value, Mapping):
        raw = {str(key): item for key, item in value.items()}
    else:
        raise SynologyRecoveryConfigurationError(
            "App-wide Synology recovery defaults are invalid."
        )
    if set(raw) - DEFAULT_FIELDS:
        raise SynologyRecoveryConfigurationError(
            "App-wide Synology recovery defaults contain unsupported fields."
        )
    if not profile_key or "/" in profile_key or "\\" in profile_key or profile_key in {".", ".."}:
        raise SynologyRecoveryConfigurationError(
            "Profile key cannot be used in a NAS destination path."
        )
    base_path = _absolute_dsm_path(
        _required_text(
            {"base_path": raw.get("base_path", DEFAULT_BASE_PATH)},
            "base_path",
            "App-wide NAS base path",
        ),
        "App-wide NAS base path",
    )
    destination_path = (
        f"{base_path}/{profile_key}" if base_path != "/" else f"/{profile_key}"
    )
    return {
        "layout": PROFILE_ROOT_LAYOUT,
        "destination_path": destination_path,
        "schedule": _required_text(
            {"schedule": raw.get("schedule", DEFAULT_SCHEDULE)},
            "schedule",
            "App-wide Cloud Sync schedule",
        ),
        "retention_policy": _required_text(
            {
                "retention_policy": raw.get(
                    "retention_policy",
                    DEFAULT_RETENTION_POLICY,
                )
            },
            "retention_policy",
            "App-wide NAS retention policy",
        ),
    }
