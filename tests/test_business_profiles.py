from __future__ import annotations

from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant

import pytest

from tabula_rasa.business_profiles import (
    BusinessProfileConfigurationError,
    load_business_profiles,
    select_profile_secrets,
)


class TestBusinessProfiles:
    def test_loads_multiple_isolated_profiles(self) -> None:
        secrets = {
            "app_password_hash": "not-used-here",
            "business_profiles": {
                "north": {
                    "name": "North Shop",
                    "spreadsheet_id": "north-sheet",
                    "google_drive": google_grant('north@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
                },
                "south": {
                    "name": "South Shop",
                    "spreadsheet_id": "south-sheet",
                    "google_drive": google_grant('south@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
                },
            },
        }

        profiles = load_business_profiles(secrets)

        assert [profile.key for profile in profiles] == ["north", "south"]
        selected = select_profile_secrets(secrets, "south")
        assert selected["spreadsheet_id"] == "south-sheet"
        assert selected["google_drive"]["authorized_email"] == "south@example.test"

    def test_rejects_removed_single_profile_format(self) -> None:
        with pytest.raises(BusinessProfileConfigurationError):
            load_business_profiles(
                {
                    "spreadsheet_id": "old-sheet",
                    "google_drive": google_grant('old@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
                }
            )

    def test_existing_hosted_profiles_with_local_fields_remain_readable(self) -> None:
        secrets = {
            "business_profiles": {
                "north": {
                    "name": "North Shop",
                    "spreadsheet_id": "north-sheet",
                    "google_drive": google_grant('north@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
                    "backup_folder_path": r"G:\Backups\North",
                    "synology_recovery": {
                        "layout": "profile-root",
                        "destination_path": "/volume1/Recovery/north",
                        "schedule": "Continuous",
                        "retention_policy": "Keep all.",
                    },
                }
            }
        }

        selected = select_profile_secrets(secrets, "north")

        assert selected["spreadsheet_id"] == "north-sheet"
        assert selected["synology_recovery"]["schedule"] == "Continuous"

    def test_rejects_service_account_profile(self) -> None:
        with pytest.raises(BusinessProfileConfigurationError):
            load_business_profiles(
                {"business_profiles": {"broken": {"spreadsheet_id": "sheet", "gcp_service_account": {}}}}
            )
