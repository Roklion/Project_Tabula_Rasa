from ._support import (
    GoogleSheetsStorageTestCase,
    Mock,
    StorageConflictError,
    StorageValidationError,
    decode_receipt_references,
    pytest,
)

class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

    def test_transaction_receipt_references_can_be_linked_and_unlinked(
        self,
    ) -> None:
        source = self.storage.create_account("Checking", "Bank")
        expense = self.storage.create_category("Software", "Expense")
        transaction = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Expense",
            amount="12.5",
            account_id=source["id"],
            category_id=expense["id"],
        )
        assert decode_receipt_references(
            transaction["receipt_references"]
        ) == []

        self.storage.link_transaction_receipt(
            transaction["id"],
            file_id="receipt123456",
            name="statement.pdf",
        )
        self.storage.link_transaction_receipt(
            transaction["id"],
            file_id="receipt123456",
            name="renamed-statement.pdf",
        )
        self.storage.link_transaction_receipt(
            transaction["id"],
            file_id="receipt234567",
            name="invoice.png",
        )
        linked = self.storage.list_transactions()[0]
        assert decode_receipt_references(
            linked["receipt_references"]
        ) == [
            {"id": "receipt123456", "name": "renamed-statement.pdf"},
            {"id": "receipt234567", "name": "invoice.png"},
        ]
        other_transaction = self.storage.create_transaction(
            txn_date="2026-07-20",
            kind="Expense",
            amount=8,
            account_id=source["id"],
            category_id=expense["id"],
        )
        with pytest.raises(
            StorageConflictError,
            match="already linked to another transaction",
        ):
            self.storage.link_transaction_receipt(
                other_transaction["id"],
                file_id="receipt123456",
                name="renamed-statement.pdf",
            )

        self.storage.unlink_transaction_receipt(
            transaction["id"],
            file_id="receipt123456",
        )

        unlinked = next(
            item
            for item in self.storage.list_transactions()
            if item["id"] == transaction["id"]
        )
        assert decode_receipt_references(
            unlinked["receipt_references"]
        ) == [{"id": "receipt234567", "name": "invoice.png"}]
        assert unlinked["id"] == transaction["id"]

    def test_uncertain_receipt_link_is_confirmed_without_a_second_write(
        self,
    ) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Software", "Expense")
        transaction = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Expense",
            amount="12.5",
            account_id=account["id"],
            category_id=category["id"],
        )
        worksheet = self.workbook.sheets["Transactions"]
        original_update = worksheet.update

        def commit_then_timeout(
            values: list[list[str]],
            range_name: str,
            **kwargs: object,
        ) -> None:
            original_update(values, range_name, **kwargs)
            raise OSError("response lost after receipt link")

        worksheet.update = Mock(side_effect=commit_then_timeout)

        self.storage.link_transaction_receipt(
            transaction["id"],
            file_id="receipt123456",
            name="statement.pdf",
        )

        assert worksheet.update.call_count == 1
        assert decode_receipt_references(
            self.storage.list_transactions(_force_refresh=True)[0][
                "receipt_references"
            ]
        ) == [{"id": "receipt123456", "name": "statement.pdf"}]

    def test_transaction_receipt_reference_validation_is_strict(self) -> None:
        with pytest.raises(
            StorageValidationError,
            match="receipt references are invalid",
        ):
            decode_receipt_references(
                [{"id": "../not-a-drive-id", "name": "receipt.pdf"}]
            )

    def test_legacy_nonportable_reference_remains_readable_and_unlinkable(
        self,
    ) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Software", "Expense")
        transaction = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Expense",
            amount="12.5",
            account_id=account["id"],
            category_id=category["id"],
        )
        worksheet = self.workbook.worksheet("Transactions")
        headers = worksheet.rows[0]
        id_index = headers.index("id")
        references_index = headers.index("receipt_references")
        row = next(
            item for item in worksheet.rows[1:] if item[id_index] == transaction["id"]
        )
        row[references_index] = (
            '[{"id":"receipt123456","name":"invoice:2026.pdf"}]'
        )

        current = self.storage.list_transactions(_force_refresh=True)[0]
        assert decode_receipt_references(current["receipt_references"]) == [
            {"id": "receipt123456", "name": "invoice:2026.pdf"}
        ]

        self.storage.unlink_transaction_receipt(
            transaction["id"],
            file_id="receipt123456",
        )
        current = self.storage.list_transactions(_force_refresh=True)[0]
        assert decode_receipt_references(current["receipt_references"]) == []

        with pytest.raises(StorageValidationError, match="unsafe"):
            self.storage.link_transaction_receipt(
                transaction["id"],
                file_id="receipt123456",
                name="invoice:2026.pdf",
            )
