from __future__ import annotations

import unittest

from quickbooks_mileage_import import (
    mileage_fingerprint,
    missing_required_columns,
    normalize_rows,
)


class QuickBooksMileageImportTests(unittest.TestCase):
    def test_normalizes_business_trip_and_converts_kilometers(self) -> None:
        result = normalize_rows(
            [
                {
                    "Trip Date": "07/20/2026",
                    "Trip Type": "Business",
                    "Business Purpose": "Client meeting",
                    "Vehicle Used": "Blue car",
                    "Starting Point": "Office",
                    "Ending Point": "Client site",
                    "Distance (km)": "10 km",
                }
            ]
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(
            result["rows"],
            [
                {
                    "_source_row": "2",
                    "trip_date": "2026-07-20",
                    "miles": "6.2",
                    "vehicle": "Blue car",
                    "start_location": "Office",
                    "destination": "Client site",
                    "business_purpose": "Client meeting",
                    "notes": "",
                }
            ],
        )

    def test_classifies_personal_unreviewed_and_invalid_rows(self) -> None:
        rows = [
            {
                "Date": "07/20/2026",
                "Type": "Personal",
                "Trip Purpose": "",
                "Vehicle": "Car",
                "Start Address": "Home",
                "End Address": "Store",
                "Distance": "2",
            },
            {
                "Date": "07/21/2026",
                "Type": "",
                "Trip Purpose": "",
                "Vehicle": "Car",
                "Start Address": "Home",
                "End Address": "Office",
                "Distance": "5",
            },
            {
                "Date": "07/22/2026",
                "Type": "Business",
                "Trip Purpose": "",
                "Vehicle": "Car",
                "Start Address": "Office",
                "End Address": "Client",
                "Distance": "8",
            },
        ]

        result = normalize_rows(rows)

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["personal_rows"], [2])
        self.assertEqual(result["unreviewed_rows"], [3])
        self.assertEqual(
            result["errors"],
            [
                "QuickBooks mileage row 4: Trip Purpose is required for "
                "business trips"
            ],
        )

    def test_required_columns_accept_quickbooks_aliases(self) -> None:
        self.assertEqual(
            missing_required_columns(
                [
                    "Trip Date",
                    "Trip Type",
                    "Business Purpose",
                    "Vehicle Used",
                    "Starting Point",
                    "Ending Point",
                    "Distance (mi)",
                ]
            ),
            [],
        )
        self.assertEqual(
            missing_required_columns(["Date", "Type"]),
            [
                "Trip Purpose",
                "Vehicle",
                "Start Address",
                "End Address",
                "Distance",
            ],
        )

    def test_fingerprint_ignores_notes_and_whitespace_case(self) -> None:
        first = {
            "trip_date": "2026-07-20",
            "miles": "8.0",
            "vehicle": "Blue Car",
            "start_location": "Main  Office",
            "destination": "CLIENT",
            "business_purpose": "Meeting",
            "notes": "First",
        }
        second = {
            **first,
            "vehicle": "blue car",
            "start_location": "main office",
            "destination": "client",
            "notes": "Second",
        }

        self.assertEqual(
            mileage_fingerprint(first),
            mileage_fingerprint(second),
        )


if __name__ == "__main__":
    unittest.main()
