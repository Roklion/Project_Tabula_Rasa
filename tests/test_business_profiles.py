from __future__ import annotations

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
                    "gcp_service_account": {"client_email": "north@example.test"},
                },
                "south": {
                    "name": "South Shop",
                    "spreadsheet_id": "south-sheet",
                    "gcp_service_account": {"client_email": "south@example.test"},
                },
            },
        }

        profiles = load_business_profiles(secrets)

        assert [profile.key for profile in profiles] == ["north", "south"]
        selected = select_profile_secrets(secrets, "south")
        assert selected["spreadsheet_id"] == "south-sheet"
        assert selected["gcp_service_account"]["client_email"] == "south@example.test"

    def test_rejects_removed_single_profile_format(self) -> None:
        with pytest.raises(BusinessProfileConfigurationError):
            load_business_profiles(
                {
                    "spreadsheet_id": "old-sheet",
                    "gcp_service_account": {"client_email": "old@example.test"},
                }
            )

    def test_rejects_profile_without_credential(self) -> None:
        with pytest.raises(BusinessProfileConfigurationError):
            load_business_profiles(
                {"business_profiles": {"broken": {"spreadsheet_id": "sheet"}}}
            )
