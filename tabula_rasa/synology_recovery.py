"""Validate optional per-profile Synology recovery-copy configuration."""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from typing import Any


SYNC_DIRECTION = "Download remote changes only"
DESTINATION_DELETIONS = "Disabled"
PROFILE_ROOT_LAYOUT = "profile-root"
LEGACY_TWO_TASK_LAYOUT = "legacy-two-task"
DEFAULT_BASE_PATH = "/volume1/Tabula_Rosa_Backups"
DEFAULT_SCHEDULE = "Continuous"
DEFAULT_RETENTION_POLICY = (
    "Retain all synchronized generations until quarterly manual review."
)
MAX_FIELD_LENGTH = 500
LEGACY_REQUIRED_FIELDS = {
    "destination_path",
    "schedule",
    "retention_policy",
}
PROFILE_ROOT_REQUIRED_FIELDS = {*LEGACY_REQUIRED_FIELDS, "layout"}
DEFAULT_FIELDS = {"base_path", "schedule", "retention_policy"}


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
    if len(normalized.strip("/").split("/")) < 2:
        raise SynologyRecoveryConfigurationError(
            f"{label} must include a Synology volume and shared folder, such as "
            "/volume1/Tabula_Rosa_Backups."
        )
    return "/" + normalized.lstrip("/")


def validate_synology_recovery_settings(value: object) -> dict[str, str]:
    """Return normalized root-sync or legacy two-task recovery metadata."""
    if not isinstance(value, Mapping):
        raise SynologyRecoveryConfigurationError(
            "Synology recovery settings are invalid."
        )
    raw = {str(key): item for key, item in value.items()}
    fields = set(raw)
    if fields not in (LEGACY_REQUIRED_FIELDS, PROFILE_ROOT_REQUIRED_FIELDS):
        raise SynologyRecoveryConfigurationError(
            "Synology recovery settings contain unsupported fields."
        )
    if "layout" in raw and raw["layout"] != PROFILE_ROOT_LAYOUT:
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
    if "layout" in raw:
        return {"layout": PROFILE_ROOT_LAYOUT, **normalized}
    return normalized


def synology_recovery_layout(value: Mapping[str, Any]) -> str:
    """Identify explicit root sync while treating the old shape as legacy."""
    return (
        PROFILE_ROOT_LAYOUT
        if value.get("layout") == PROFILE_ROOT_LAYOUT
        else LEGACY_TWO_TASK_LAYOUT
    )


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
