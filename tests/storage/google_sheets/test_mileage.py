from ._support import (
    GoogleSheetsStorageTestCase,
    Mock,
    StorageValidationError,
    pytest,
)

class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

    def test_mileage_trip_crud_filtering_and_validation(self) -> None:
        first = self.storage.create_mileage_trip(
            trip_date="2026-07-18",
            miles="12.34",
            vehicle="Blue car",
            start_location="Office",
            destination="Client site",
            business_purpose="Project meeting",
            notes="Tolls paid separately",
        )
        second = self.storage.create_mileage_trip(
            trip_date="2026-07-20",
            miles=5,
            start_location="Client site",
            destination="Office",
            business_purpose="Return trip",
        )

        assert first["miles"] == "12.3"
        assert [trip["id"] for trip in self.storage.list_mileage_trips()] == [
            second["id"],
            first["id"],
        ]
        assert [
            trip["id"] for trip in self.storage.list_mileage_trips(end="2026-07-19")
        ] == [first["id"]]

        edited = self.storage.edit_mileage_trip(
            first["id"],
            miles=14.2,
            destination="Updated client site",
        )
        assert edited["miles"] == "14.2"
        assert edited["created_at"] == first["created_at"]

        self.storage.delete_mileage_trip(second["id"])
        assert [trip["id"] for trip in self.storage.list_mileage_trips()] == [
            first["id"]
        ]
        with pytest.raises(StorageValidationError):
            self.storage.create_mileage_trip(
                trip_date="2026-07-20",
                miles=0,
                start_location="Office",
                destination="Client",
                business_purpose="Meeting",
            )
        with pytest.raises(StorageValidationError):
            self.storage.create_mileage_trip(
                trip_date="2026-07-20",
                miles=1,
                start_location="Office",
                destination="",
                business_purpose="Meeting",
            )

    def test_mileage_round_trip_creates_reversed_entries_in_one_batch(self) -> None:
        worksheet = self.workbook.sheets["Mileage"]
        original_append_many = worksheet.append_rows
        worksheet.append_rows = Mock(wraps=original_append_many)

        records = self.storage.create_mileage_round_trip(
            trip_date="2026-07-20",
            miles=12.6,
            vehicle="Blue car",
            start_location="Office",
            destination="Client site",
            business_purpose="Project meeting",
            notes="Parking receipt saved",
        )

        assert len(records) == 2
        assert worksheet.append_rows.call_count == 1
        assert records[0]["id"] != records[1]["id"]
        assert records[0]["created_at"] == records[1]["created_at"]
        assert [
            (
                record["start_location"],
                record["destination"],
                record["miles"],
            )
            for record in records
        ] == [
            ("Office", "Client site", "12.6"),
            ("Client site", "Office", "12.6"),
        ]
        assert {record["business_purpose"] for record in records} == {"Project meeting"}
        listed = self.storage.list_mileage_trips()
        assert len(listed) == 2
        assert [
            (record["start_location"], record["destination"])
            for record in listed
        ] == [
            ("Client site", "Office"),
            ("Office", "Client site"),
        ]

    def test_batch_append_rejects_duplicate_input_ids_before_writing(self) -> None:
        worksheet = self.workbook.sheets["Accounts"]
        worksheet.append_rows = Mock(wraps=worksheet.append_rows)

        with pytest.raises(StorageValidationError, match="Duplicate ID"):
            self.storage._append_many(
                "Accounts",
                [{"id": "duplicate"}, {"id": "duplicate"}],
            )

        worksheet.append_rows.assert_not_called()

    def test_append_helpers_reject_missing_ids_before_writing(self) -> None:
        worksheet = self.workbook.sheets["Accounts"]
        worksheet.append_row = Mock(wraps=worksheet.append_row)
        worksheet.append_rows = Mock(wraps=worksheet.append_rows)

        with pytest.raises(StorageValidationError, match="ID is required"):
            self.storage._append("Accounts", {"name": "Missing ID"})
        with pytest.raises(StorageValidationError, match="ID is required"):
            self.storage._append_many("Accounts", [{"name": "Missing ID"}])

        worksheet.append_row.assert_not_called()
        worksheet.append_rows.assert_not_called()

    def test_mileage_round_trip_supports_different_return_miles(self) -> None:
        worksheet = self.workbook.sheets["Mileage"]
        original_append_many = worksheet.append_rows
        worksheet.append_rows = Mock(wraps=original_append_many)

        records = self.storage.create_mileage_round_trip(
            trip_date="2026-07-20",
            miles=12.6,
            return_miles=13.1,
            vehicle="Blue car",
            start_location="Office",
            destination="Client site",
            business_purpose="Project meeting",
        )

        assert worksheet.append_rows.call_count == 1
        assert records[0]["id"] != records[1]["id"]
        assert records[0]["miles"] == "12.6"
        assert records[1]["miles"] == "13.1"
        assert records[0]["start_location"] == "Office"
        assert records[0]["destination"] == "Client site"
        assert records[1]["start_location"] == "Client site"
        assert records[1]["destination"] == "Office"
        assert all("round_trip" not in record for record in records)
        assert set(records[0]) == {
            "id",
            "trip_date",
            "miles",
            "vehicle",
            "start_location",
            "destination",
            "business_purpose",
            "notes",
            "tag_ids",
            "created_at",
        }
        assert not any(
            field in records[0]
            for field in (
                "start_place_id",
                "destination_place_id",
                "distance_source",
                "calculated_miles",
                "route_calculated_at",
                "distanceMeters",
            )
        )
        listed = self.storage.list_mileage_trips()
        assert {record["id"] for record in listed} == {
            record["id"] for record in records
        }
        assert {record["miles"] for record in listed} == {"12.6", "13.1"}

    def test_quickbooks_mileage_preview_import_and_duplicates(self) -> None:
        business = {
            "Date": "07/20/2026",
            "Type": "Business",
            "Trip Purpose": "Client meeting",
            "Vehicle": "Blue car",
            "Start Address": "Office",
            "End Address": "Client site",
            "Distance": "12.4",
            "Deduction": "8.68",
            "Logging Method": "Auto-tracked",
        }
        personal = {
            **business,
            "Date": "07/21/2026",
            "Type": "Personal",
            "Trip Purpose": "",
        }
        unreviewed = {
            **business,
            "Date": "07/22/2026",
            "Type": "",
            "Trip Purpose": "",
        }
        invalid = {
            **business,
            "Date": "07/23/2026",
            "Trip Purpose": "",
        }

        blocked = self.storage.preview_quickbooks_mileage(
            [business, personal, unreviewed, invalid]
        )
        assert blocked["summary"]["ready"] == 1
        assert blocked["summary"]["personal_skipped"] == 1
        assert blocked["summary"]["unreviewed_skipped"] == 1
        assert len(blocked["errors"]) == 1
        with pytest.raises(StorageValidationError):
            self.storage.import_quickbooks_mileage(
                [business, personal, unreviewed, invalid]
            )
        assert self.storage.list_mileage_trips() == []

        preview = self.storage.preview_quickbooks_mileage(
            [business, business, personal, unreviewed]
        )
        assert preview["summary"] == {
            "ready": 1,
            "duplicates": 1,
            "personal_skipped": 1,
            "unreviewed_skipped": 1,
        }
        assert preview["duplicate_rows"] == [3]

        imported = self.storage.import_quickbooks_mileage(
            [business, business, personal, unreviewed]
        )
        assert len(imported) == 1
        assert imported[0]["miles"] == "12.4"
        assert imported[0]["business_purpose"] == "Client meeting"

        repeated = self.storage.preview_quickbooks_mileage([business])
        assert repeated["summary"]["ready"] == 0
        assert repeated["duplicate_rows"] == [2]

    def test_quickbooks_mileage_batch_import_reuses_tag_snapshot(self) -> None:
        tags_sheet = self.workbook.sheets["Tags"]
        tags_sheet.get_all_values = Mock(wraps=tags_sheet.get_all_values)
        rows = [
            {
                "Date": f"07/{index:02d}/2026",
                "Type": "Business",
                "Trip Purpose": "Client meeting",
                "Vehicle": "Blue car",
                "Start Address": "Office",
                "End Address": "Client site",
                "Distance": "12.4",
                "Deduction": "8.68",
                "Logging Method": "Auto-tracked",
            }
            for index in range(1, 11)
        ]

        imported = self.storage.import_quickbooks_mileage(rows)

        assert len(imported) == 10
        assert tags_sheet.get_all_values.call_count == 1
