from ._support import (
    GoogleSheetsStorageTestCase,
    FakeWorkbook,
    GoogleSheetsStorage,
    StorageValidationError,
    json,
    pytest,
)


class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

    def test_tags_are_profile_local_and_deduplicated_by_normalized_name(self) -> None:
        first = self.storage.create_tag("  Client   Visit ")
        duplicate = self.storage.create_tag("client visit")

        assert duplicate["id"] == first["id"]
        assert duplicate["name"] == "Client   Visit"
        assert self.storage.list_tags()[0]["name"] == "Client   Visit"

        inactive = self.storage.create_tag("Internal", active=False)
        assert self.storage.list_tags(active_only=True) == [first]
        reactivated = self.storage.create_tag(" internal ")
        assert reactivated["id"] == inactive["id"]
        assert reactivated["active"] == "TRUE"

        other = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        other_tag = other.create_tag("client visit")
        assert other_tag["id"] != first["id"]

    def test_transaction_and_mileage_tags_round_trip_and_resolve_names(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        first = self.storage.create_tag("Client")
        second = self.storage.create_tag("Follow-up")
        transaction = self.storage.create_transaction(
            txn_date="2026-09-01",
            kind="Expense",
            amount=10,
            account_id=account["id"],
            category_id=category["id"],
            tag_ids=[second["id"], first["id"]],
        )
        mileage = self.storage.create_mileage_trip(
            trip_date="2026-09-01",
            miles=4.5,
            start_location="Office",
            destination="Client",
            business_purpose="Visit",
            tag_ids=[first["id"], second["id"]],
        )

        assert transaction["tag_ids"] == json.dumps(
            sorted([first["id"], second["id"]]), separators=(",", ":")
        )
        listed_transaction = self.storage.list_transactions()[0]
        listed_mileage = self.storage.list_mileage_trips()[0]
        assert listed_transaction["tag_ids"] == sorted([first["id"], second["id"]])
        assert listed_transaction["tags"] == [
            {first["id"]: "Client", second["id"]: "Follow-up"}[tag_id]
            for tag_id in listed_transaction["tag_ids"]
        ]
        assert listed_mileage["tag_ids"] == sorted([first["id"], second["id"]])
        assert listed_mileage["tags"] == [
            {first["id"]: "Client", second["id"]: "Follow-up"}[tag_id]
            for tag_id in listed_mileage["tag_ids"]
        ]

        edited = self.storage.edit_transaction(transaction["id"], tag_ids=[first["id"]])
        edited_mileage = self.storage.edit_mileage_trip(
            mileage["id"], tag_ids=[second["id"]]
        )
        assert edited["tag_ids"] == json.dumps([first["id"]], separators=(",", ":"))
        assert edited_mileage["tag_ids"] == json.dumps(
            [second["id"]], separators=(",", ":")
        )

    @pytest.mark.parametrize("value", ["not-json", "{}", "[1]", '["tag", "tag"]'])
    def test_tag_ids_reject_invalid_payloads(self, value: str) -> None:
        with pytest.raises(StorageValidationError):
            self.storage._prepare_mileage_trip(
                {
                    "trip_date": "2026-09-01",
                    "miles": 1,
                    "start_location": "A",
                    "destination": "B",
                    "business_purpose": "C",
                    "tag_ids": value,
                }
            )

    def test_tag_ids_reject_unknown_references(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        with pytest.raises(StorageValidationError, match="Tag does not exist"):
            self.storage.create_transaction(
                txn_date="2026-09-01",
                kind="Expense",
                amount=10,
                account_id=account["id"],
                category_id=category["id"],
                tag_ids=["missing-tag"],
            )

    def test_invalid_tag_does_not_persist_new_payee(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")

        with pytest.raises(StorageValidationError, match="Tag does not exist"):
            self.storage.create_transaction(
                txn_date="2026-09-01",
                kind="Expense",
                amount=10,
                account_id=account["id"],
                category_id=category["id"],
                new_payee_name="Orphan payee",
                tag_ids=["missing-tag"],
            )

        assert self.storage.list_payees() == []
        assert self.storage.list_transactions() == []

    def test_invalid_mileage_does_not_create_inline_tag(self) -> None:
        with pytest.raises(StorageValidationError, match="Miles must be greater"):
            self.storage.create_mileage_trip(
                trip_date="2026-09-01",
                miles=0,
                start_location="A",
                destination="B",
                business_purpose="C",
                new_tag_name="Should not persist",
            )

        assert self.storage.list_tags() == []

    def test_invalid_round_trip_return_does_not_create_inline_tag(self) -> None:
        with pytest.raises(StorageValidationError, match="Miles must be greater"):
            self.storage.create_mileage_round_trip(
                trip_date="2026-09-01",
                miles=1,
                return_miles=0,
                start_location="A",
                destination="B",
                business_purpose="C",
                new_tag_name="Should not persist",
            )

        assert self.storage.list_tags() == []
        assert self.storage.list_mileage_trips() == []
