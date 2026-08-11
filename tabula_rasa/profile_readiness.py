"""Sanitized readiness contracts for local profile administration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from scripts.export_streamlit_secrets import project_hosted_profiles


ReadinessStatus = Literal["incomplete", "ready-local", "ready-hosted"]


@dataclass(frozen=True)
class ProfileReadiness:
    """Safe status information suitable for rendering in the admin UI."""

    status: ReadinessStatus
    missing_steps: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    hosted_export_needed: bool = False


def profile_configuration_readiness(
    profile_key: str,
    settings: Mapping[str, Any],
    *,
    hosted_profiles: Mapping[str, Any] | None = None,
    validation_errors: tuple[str, ...] = (),
) -> ProfileReadiness:
    """Return a secret-free readiness report for one validated local profile."""
    missing: list[str] = []
    drive = settings.get("google_drive")
    if isinstance(drive, Mapping):
        if not isinstance(drive.get("storage_root"), Mapping):
            missing.append("Select or create the Google Drive storage root.")
        if not isinstance(drive.get("receipt_folder"), Mapping) or not isinstance(
            drive.get("backup_folder"), Mapping
        ):
            missing.append(
                "Provision the Receipts and Ledger Backups folders under the root."
            )

    errors = tuple(str(error) for error in validation_errors if str(error).strip())
    if errors:
        missing.append("Resolve the reported validation failure and run the check again.")
    if missing:
        return ProfileReadiness(
            status="incomplete",
            missing_steps=tuple(dict.fromkeys(missing)),
            validation_errors=errors,
        )

    hosted_export_needed = True
    if hosted_profiles is not None:
        try:
            projected = project_hosted_profiles({profile_key: settings})[profile_key]
        except ValueError:
            projected = None
        current = hosted_profiles.get(profile_key)
        hosted_export_needed = projected != current
    return ProfileReadiness(
        status="ready-local" if hosted_export_needed else "ready-hosted",
        hosted_export_needed=hosted_export_needed,
    )
