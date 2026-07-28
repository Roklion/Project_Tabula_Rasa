from __future__ import annotations

import pytest

from tabula_rasa.synology_recovery import (
    SynologyRecoveryConfigurationError,
    validate_synology_recovery_settings,
)


def test_normalizes_synology_recovery_settings() -> None:
    assert validate_synology_recovery_settings(
        {
            "destination_path": " /volume1/Backups/TabulaRasa/north ",
            "schedule": " Continuous ",
            "retention_policy": " Keep until manual review. ",
        }
    ) == {
        "destination_path": "/volume1/Backups/TabulaRasa/north",
        "schedule": "Continuous",
        "retention_policy": "Keep until manual review.",
    }


@pytest.mark.parametrize(
    "settings",
    (
        {},
        {
            "destination_path": "relative/path",
            "schedule": "Continuous",
            "retention_policy": "Keep all",
        },
        {
            "destination_path": "/volume1/Backups/north",
            "schedule": "",
            "retention_policy": "Keep all",
        },
        {
            "destination_path": "/volume1/Backups/north",
            "schedule": "Continuous",
            "retention_policy": "Keep all",
            "password": "must-not-be-stored",
        },
    ),
)
def test_rejects_incomplete_or_unsupported_synology_settings(
    settings: object,
) -> None:
    with pytest.raises(SynologyRecoveryConfigurationError):
        validate_synology_recovery_settings(settings)
