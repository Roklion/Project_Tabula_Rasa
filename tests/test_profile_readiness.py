from __future__ import annotations

from tabula_rasa.profile_readiness import profile_configuration_readiness


def _settings(**overrides: object) -> dict[str, object]:
    settings: dict[str, object] = {
        "name": "North Shop",
        "spreadsheet_id": "north-sheet",
        "gcp_service_account": {
            "type": "service_account",
            "client_email": "ledger@example.test",
            "private_key": "never-rendered",
        },
    }
    settings.update(overrides)
    return settings


def _drive_settings() -> dict[str, object]:
    return {
        "authorized_email": "owner@example.test",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/drive.file"],
        "storage_root": {"id": "root123456", "name": "North Storage"},
        "receipt_folder": {"id": "receipts123456", "name": "Receipts"},
        "backup_folder": {"id": "backup123456", "name": "Ledger Backups"},
    }


def test_sheets_only_profile_is_ready_locally_without_optional_destinations() -> None:
    report = profile_configuration_readiness("north", _settings())

    assert report.status == "ready-local"
    assert report.missing_steps == ()
    assert report.hosted_export_needed


def test_partial_drive_configuration_is_incomplete() -> None:
    report = profile_configuration_readiness(
        "north",
        _settings(google_drive={"refresh_token": "present"}),
    )

    assert report.status == "incomplete"
    assert report.missing_steps == (
        "Select or create the Google Drive storage root.",
        "Provision the Receipts and Ledger Backups folders under the root.",
    )


def test_matching_hosted_projection_is_ready_hosted() -> None:
    settings = _settings(google_drive=_drive_settings())
    from scripts.export_streamlit_secrets import project_hosted_profiles

    hosted = project_hosted_profiles({"north": settings})
    report = profile_configuration_readiness(
        "north",
        settings,
        hosted_profiles=hosted,
    )

    assert report.status == "ready-hosted"
    assert not report.hosted_export_needed


def test_local_only_validation_failure_is_sanitized_and_actionable() -> None:
    report = profile_configuration_readiness(
        "north",
        _settings(),
        validation_errors=("Sheets validation failed",),
    )

    assert report.status == "incomplete"
    assert report.validation_errors == ("Sheets validation failed",)
    assert "credential" not in " ".join(report.validation_errors).casefold()
