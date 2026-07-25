from __future__ import annotations

import unittest

from receipt_storage import (
    GoogleDriveReceiptStorage,
    parse_drive_folder_id,
    receipt_filename,
)
from storage import StorageUnavailableError, StorageValidationError


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"id": "file-id", "name": "txn-1-receipt.pdf"}


class _Session:
    def __init__(self) -> None:
        self.request: dict | None = None

    def post(self, url: str, **kwargs):
        self.request = {"url": url, **kwargs}
        return _Response()


class _QuotaResponse(_Response):
    status_code = 403

    def json(self) -> dict:
        return {
            "error": {
                "errors": [{"reason": "storageQuotaExceeded"}],
            }
        }


class _QuotaSession(_Session):
    def post(self, url: str, **kwargs):
        self.request = {"url": url, **kwargs}
        return _QuotaResponse()


class ReceiptStorageTests(unittest.TestCase):
    def test_parses_folder_url_and_builds_safe_prefixed_name(self) -> None:
        self.assertEqual(
            parse_drive_folder_id(
                "https://drive.google.com/drive/folders/receiptfolder123456"
            ),
            "receiptfolder123456",
        )
        self.assertEqual(
            receipt_filename("transaction-id", "../../shop:receipt.pdf"),
            "transaction-id-shop_receipt.pdf",
        )

    def test_upload_targets_configured_folder(self) -> None:
        session = _Session()
        storage = GoogleDriveReceiptStorage(
            object(), "receiptfolder123456", session=session
        )

        uploaded = storage.upload(
            "txn-1", "receipt.pdf", b"%PDF-data", "application/pdf"
        )

        self.assertEqual(uploaded["id"], "file-id")
        self.assertIn(b'"parents":["receiptfolder123456"]', session.request["data"])
        self.assertIn(b'"name":"txn-1-receipt.pdf"', session.request["data"])
        self.assertIn("supportsAllDrives=true", session.request["url"])

    def test_rejects_unsupported_or_empty_upload(self) -> None:
        storage = GoogleDriveReceiptStorage(
            object(), "receiptfolder123456", session=_Session()
        )
        with self.assertRaises(StorageValidationError):
            storage.upload("txn-1", "receipt.exe", b"data")
        with self.assertRaises(StorageValidationError):
            storage.upload("txn-1", "receipt.pdf", b"")

    def test_explains_service_account_storage_quota_failure(self) -> None:
        storage = GoogleDriveReceiptStorage(
            object(), "receiptfolder123456", session=_QuotaSession()
        )

        with self.assertRaises(StorageUnavailableError) as raised:
            storage.upload("txn-1", "receipt.pdf", b"%PDF-data")

        self.assertIn("Shared Drive", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
