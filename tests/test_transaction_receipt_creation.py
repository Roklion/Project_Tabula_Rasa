from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import streamlit as st

from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.page_renderers.transactions.receipts import (
    handle_confirmed_transaction_receipts,
    new_receipt_creation_workflow,
    prepare_receipt_uploads,
    process_receipt_recovery,
    receipt_creation_counts,
    receipt_creation_workflow_key,
    render_receipt_creation_recovery,
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
    session_state = {
        receipt_creation_workflow_key("north"): north,
        receipt_creation_workflow_key("south"): south,
    }

    with (
        patch.object(st, "session_state", session_state),
        patch.object(st, "info") as info,
        patch.object(st, "warning"),
        patch.object(st, "caption"),
        patch.object(st, "button", return_value=False),
    ):
        assert render_receipt_creation_recovery(
            SimpleNamespace(profile_key="south", profile_secrets={})
        )

    info.assert_called_once_with(
        "Transaction south-txn is saved in Google Sheets. "
        "Receipt processing can be resumed independently."
    )
    assert session_state[receipt_creation_workflow_key("north")] is north
    assert session_state[receipt_creation_workflow_key("south")] is south


def test_confirmed_upload_metadata_failure_does_not_upload_again() -> None:
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [
            {
                "key": "metadata-failure",
                "original_name": "receipt.pdf",
                "content": b"receipt",
                "mime_type": "application/pdf",
                "linked": False,
            }
        ],
    )
    uploaded: list[str] = []

    def upload(item: Mapping[str, object]) -> Mapping[str, object]:
        uploaded.append(str(item["key"]))
        return {
            "id": "drive123456",
            "name": "receipt.pdf",
            "mimeType": "application/pdf",
            "size": "7",
        }

    for _ in range(2):
        process_receipt_recovery(
            workflow,
            upload_receipt=upload,
            link_receipt=lambda _reference: None,
        )

    assert uploaded == ["metadata-failure"]
    assert receipt_creation_counts(workflow) == (0, 1)
    assert "metadata" in workflow["receipts"][0]["error"]


def test_receipt_recovery_uses_selected_profile_clients() -> None:
    session_state: dict[str, object] = {}
    drive_profiles: list[str] = []
    storage_profiles: list[str] = []

    def drive_client_for(profile_key: str, _revision: str):
        drive_profiles.append(profile_key)

        class DriveClient:
            def upload_receipt(self, **_kwargs: object) -> Mapping[str, object]:
                receipt_id = "a" if profile_key == "north" else "b"
                return _drive_file(receipt_id, f"{profile_key}.pdf")

        return DriveClient()

    def make_context(profile_key: str) -> SimpleNamespace:
        class StorageClient:
            def link_transaction_receipt(
                self,
                _transaction_id: str,
                *,
                reference: Mapping[str, object],
            ) -> None:
                storage_profiles.append(str(reference["original_filename"]).split(".")[0])
                raise RuntimeError("link pending")

        return SimpleNamespace(
            profile_key=profile_key,
            storage=StorageClient(),
            profile_secrets={"google_drive": {"receipt_folder": {"id": "folder"}}},
            configuration_revision="1",
            get_drive_client=drive_client_for,
            schedule_widget_reset=lambda _flag: None,
        )

    receipt = {
        "key": "receipt",
        "original_name": "receipt.pdf",
        "content": b"receipt",
        "mime_type": "application/pdf",
        "linked": False,
    }
    with patch.object(st, "session_state", session_state):
        handle_confirmed_transaction_receipts(
            make_context("north"), {"id": "north-txn"}, [receipt]
        )
        handle_confirmed_transaction_receipts(
            make_context("south"), {"id": "south-txn"}, [receipt]
        )

    assert drive_profiles == ["north", "south"]
    assert storage_profiles == ["north", "south"]
    assert session_state[receipt_creation_workflow_key("north")]["transaction_id"] == (
        "north-txn"
    )
    assert session_state[receipt_creation_workflow_key("south")]["transaction_id"] == (
        "south-txn"
    )


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
