from __future__ import annotations

from collections.abc import Mapping

import pytest

from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.page_renderers.transactions.receipts import (
    new_receipt_creation_workflow,
    prepare_receipt_uploads,
    process_receipt_recovery,
    receipt_creation_counts,
)


class UploadedFile:
    def __init__(self, name: str, content: bytes, mime_type: str) -> None:
        self.name = name
        self.type = mime_type
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


def _drive_file(receipt_id: str, name: str) -> dict[str, object]:
    return {
        "id": f"drive-{receipt_id}123456",
        "name": name,
        "mimeType": "application/pdf",
        "size": "7",
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaReceiptId": receipt_id * 32,
            "tabulaRasaSha256": "b" * 64,
            "tabulaRasaOriginalName": name,
        },
    }


def test_prepare_receipts_preserves_duplicate_names_as_independent_items() -> None:
    prepared = prepare_receipt_uploads(
        [
            UploadedFile("receipt.pdf", b"first", "application/pdf"),
            UploadedFile("receipt.pdf", b"second", "application/pdf"),
        ]
    )

    assert [item["original_name"] for item in prepared] == [
        "receipt.pdf",
        "receipt.pdf",
    ]
    assert prepared[0]["key"] != prepared[1]["key"]
    assert [item["linked"] for item in prepared] == [False, False]


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("receipt.txt", b"receipt", "must be PDF"),
        ("receipt.pdf", b"", "non-empty"),
    ],
)
def test_prepare_receipts_rejects_invalid_files_before_sheets_write(
    name: str,
    content: bytes,
    message: str,
) -> None:
    with pytest.raises(GoogleDriveAccessError, match=message):
        prepare_receipt_uploads(
            [UploadedFile(name, content, "application/octet-stream")]
        )


def test_partial_link_failure_retries_only_unresolved_receipt() -> None:
    receipts = [
        {
            "key": "first",
            "original_name": "receipt.pdf",
            "content": b"first",
            "mime_type": "application/pdf",
            "linked": False,
        },
        {
            "key": "second",
            "original_name": "receipt.pdf",
            "content": b"second",
            "mime_type": "application/pdf",
            "linked": False,
        },
    ]
    workflow = new_receipt_creation_workflow("txn-1", receipts)
    uploaded: list[str] = []
    linked: list[str] = []
    fail_second_link = {"value": True}

    def upload(item: Mapping[str, object]) -> Mapping[str, object]:
        key = str(item["key"])
        uploaded.append(key)
        return _drive_file(
            "a" if key == "first" else "c",
            str(item["original_name"]),
        )

    def link(reference: Mapping[str, object]) -> None:
        receipt_id = str(reference["receipt_id"])
        linked.append(receipt_id)
        if receipt_id.startswith("c") and fail_second_link["value"]:
            raise RuntimeError("Sheets link failed")

    process_receipt_recovery(
        workflow,
        upload_receipt=upload,
        link_receipt=link,
    )

    assert receipt_creation_counts(workflow) == (1, 1)
    assert uploaded == ["first", "second"]
    assert [item["linked"] for item in workflow["receipts"]] == [True, False]

    fail_second_link["value"] = False
    process_receipt_recovery(
        workflow,
        upload_receipt=upload,
        link_receipt=link,
    )

    assert receipt_creation_counts(workflow) == (2, 0)
    assert uploaded == ["first", "second"]
    assert len(linked) == 3


def test_receipt_recovery_state_is_scoped_to_profile() -> None:
    north = new_receipt_creation_workflow("north-txn", [], profile_key="north")
    south = new_receipt_creation_workflow("south-txn", [], profile_key="south")

    assert north["profile_key"] == "north"
    assert south["profile_key"] == "south"


def test_upload_failure_does_not_stop_later_receipts() -> None:
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [
            {
                "key": "failed",
                "original_name": "failed.pdf",
                "content": b"failed",
                "mime_type": "application/pdf",
                "linked": False,
            },
            {
                "key": "successful",
                "original_name": "successful.pdf",
                "content": b"successful",
                "mime_type": "application/pdf",
                "linked": False,
            },
        ],
    )

    def upload(item: Mapping[str, object]) -> Mapping[str, object]:
        if item["key"] == "failed":
            raise RuntimeError("Drive upload failed")
        return _drive_file("d", str(item["original_name"]))

    process_receipt_recovery(
        workflow,
        upload_receipt=upload,
        link_receipt=lambda _reference: None,
    )

    assert [item["linked"] for item in workflow["receipts"]] == [False, True]
    assert receipt_creation_counts(workflow) == (1, 1)
