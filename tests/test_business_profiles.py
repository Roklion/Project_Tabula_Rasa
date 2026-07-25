from __future__ import annotations

import unittest

from business_profiles import (
    BusinessProfileConfigurationError,
    load_business_profiles,
    select_profile_secrets,
)


class BusinessProfileTests(unittest.TestCase):
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

        self.assertEqual([profile.key for profile in profiles], ["north", "south"])
        selected = select_profile_secrets(secrets, "south")
        self.assertEqual(selected["spreadsheet_id"], "south-sheet")
        self.assertEqual(
            selected["gcp_service_account"]["client_email"], "south@example.test"
        )

    def test_rejects_removed_single_profile_format(self) -> None:
        with self.assertRaises(BusinessProfileConfigurationError):
            load_business_profiles(
                {
                    "spreadsheet_id": "old-sheet",
                    "gcp_service_account": {"client_email": "old@example.test"},
                }
            )

    def test_rejects_profile_without_credential(self) -> None:
        with self.assertRaises(BusinessProfileConfigurationError):
            load_business_profiles(
                {"business_profiles": {"broken": {"spreadsheet_id": "sheet"}}}
            )


if __name__ == "__main__":
    unittest.main()
