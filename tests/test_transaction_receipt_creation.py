from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import streamlit as st

from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.page_renderers.transactions.receipts import (
    handle_confirmed_transaction_receipts,
    clear_receipt_creation_recovery,
    new_receipt_creation_workflow,
    prepare_receipt_uploads,
    process_receipt_recovery,
    receipt_creation_counts,
    receipt_creation_workflow_key,
    render_receipt_creation_recovery,
    _workflow_configuration_matches,
    _link_recovery_configuration_matches,
    _workflow_has_uploaded_receipt,
    _transaction_still_exists,
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


def test_prepare_receipts_rejects_more_than_manifest_limit_before_sheets_write() -> None:
    uploaded = UploadedFile("receipt.pdf", b"receipt", "application/pdf")

    with pytest.raises(GoogleDriveAccessError, match="no more than 100"):
        prepare_receipt_uploads([uploaded] * 101)


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
    assert workflow["receipts"][0]["content"] == b""
    assert workflow["receipts"][1]["content"] == b""

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
        "receipt_id": "a" * 32,
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


def test_confirmed_receipt_link_invalidates_prepared_export_revision() -> None:
    revision_changes = Mock()
    linked: list[str] = []

    class DriveClient:
        def upload_receipt(self, **_kwargs: object) -> Mapping[str, object]:
            return _drive_file("a", "receipt.pdf")

    class StorageClient:
        def link_transaction_receipt(
            self,
            transaction_id: str,
            *,
            reference: Mapping[str, object],
        ) -> None:
            linked.append(f"{transaction_id}:{reference['id']}")

    context = SimpleNamespace(
        profile_key="north",
        storage=StorageClient(),
        profile_secrets={
            "spreadsheet_id": "north-sheet",
            "google_drive": {"receipt_folder": {"id": "north-folder"}},
        },
        configuration_revision="revision",
        get_drive_client=lambda *_args: DriveClient(),
        schedule_widget_reset=lambda _flag: None,
        mark_workbook_data_changed=revision_changes,
    )
    receipt = {
        "key": "receipt",
        "original_name": "receipt.pdf",
        "content": b"receipt",
        "mime_type": "application/pdf",
        "receipt_id": "a" * 32,
        "linked": False,
    }

    with patch.object(st, "session_state", {}):
        handle_confirmed_transaction_receipts(
            context,
            {"id": "north-txn"},
            [receipt],
        )

    assert linked == ["north-txn:drive-a123456"]
    revision_changes.assert_called_once_with()


def test_deleted_transaction_clears_only_matching_recovery() -> None:
    session_state: dict[str, object] = {}
    north_context = SimpleNamespace(profile_key="north")
    session_state[receipt_creation_workflow_key("north")] = (
        new_receipt_creation_workflow(
            "north-txn",
            [],
            profile_key="north",
        )
    )
    with patch.object(st, "session_state", session_state):
        clear_receipt_creation_recovery(north_context, "other-txn")
        assert receipt_creation_workflow_key("north") in session_state
        clear_receipt_creation_recovery(north_context, "north-txn")

    assert receipt_creation_workflow_key("north") not in session_state


def test_receipt_recovery_refuses_changed_profile_configuration() -> None:
    workflow = new_receipt_creation_workflow(
        "north-txn",
        [],
        profile_key="north",
        configuration_revision="old-revision",
        spreadsheet_id="old-sheet",
        receipt_folder_id="old-folder",
    )
    context = SimpleNamespace(
        configuration_revision="new-revision",
        profile_secrets={"spreadsheet_id": "new-sheet"},
    )

    assert not _workflow_configuration_matches(
        context,
        workflow,
        {"id": "new-folder"},
    )
    assert "configuration changed" in workflow["configuration_error"]


def test_receipt_recovery_ignores_unrelated_profile_revision_change() -> None:
    workflow = new_receipt_creation_workflow(
        "north-txn",
        [],
        profile_key="north",
        configuration_revision="old-revision",
        spreadsheet_id="north-sheet",
        receipt_folder_id="north-folder",
    )
    context = SimpleNamespace(
        configuration_revision="new-revision",
        profile_secrets={"spreadsheet_id": "north-sheet"},
    )

    assert _workflow_configuration_matches(
        context,
        workflow,
        {"id": "north-folder"},
    )
    assert "configuration_error" not in workflow


def test_transaction_recovery_rechecks_fresh_sheets_data() -> None:
    storage = SimpleNamespace(
        list_transactions=lambda **kwargs: (
            assert_force_refresh(kwargs),
            [{"id": "txn-1"}],
        )[1]
    )
    context = SimpleNamespace(storage=storage)

    assert _transaction_still_exists(context, "txn-1")


def test_transaction_recovery_detects_uploaded_receipt_pointer() -> None:
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [
            {
                "linked": False,
                "reference": {"id": "receipt123456"},
            }
        ],
    )

    assert _workflow_has_uploaded_receipt(workflow)
    assert not _workflow_has_uploaded_receipt(
        new_receipt_creation_workflow("txn-2", [{"linked": False}])
    )
    uncertain_workflow = new_receipt_creation_workflow(
        "txn-3",
        [{"linked": False, "upload_uncertain": True}],
    )
    assert _workflow_has_uploaded_receipt(uncertain_workflow)


def test_transaction_recovery_does_not_upload_after_cross_session_deletion() -> None:
    storage = SimpleNamespace(
        list_transactions=lambda **kwargs: (
            assert_force_refresh(kwargs),
            [],
        )[1]
    )
    context = SimpleNamespace(
        profile_key="north",
        storage=storage,
        profile_secrets={"google_drive": {"receipt_folder": {"id": "folder"}}},
        configuration_revision="revision",
        get_drive_client=lambda *_args: (_ for _ in ()).throw(
            AssertionError("Drive upload must not start after deletion")
        ),
        schedule_widget_reset=lambda _flag: None,
    )
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [
            {
                "key": "receipt",
                "original_name": "receipt.pdf",
                "content": b"receipt",
                "mime_type": "application/pdf",
                "linked": False,
            }
        ],
        profile_key="north",
        configuration_revision="revision",
        spreadsheet_id="",
        receipt_folder_id="folder",
    )
    session_state = {receipt_creation_workflow_key("north"): workflow}

    with (
        patch.object(st, "session_state", session_state),
        patch.object(st, "info"),
        patch.object(st, "warning"),
        patch.object(st, "error"),
        patch.object(st, "caption"),
        patch.object(st, "button", return_value=True),
        patch.object(st, "rerun", side_effect=RuntimeError("rerun")),
    ):
        with pytest.raises(RuntimeError, match="rerun"):
            render_receipt_creation_recovery(context)

    assert receipt_creation_workflow_key("north") not in session_state
    assert session_state["write_success_notice"] == (
        "The saved transaction no longer exists. "
        "Start a new transaction and select its receipts again."
    )


def assert_force_refresh(kwargs: Mapping[str, object]) -> None:
    assert kwargs == {"_force_refresh": True}


def test_post_create_link_recovery_refuses_changed_storage_configuration() -> None:
    context = SimpleNamespace(
        profile_secrets={"spreadsheet_id": "new-sheet"},
    )
    recovery = {
        "spreadsheet_id": "old-sheet",
        "receipt_folder_id": "old-folder",
    }

    assert not _link_recovery_configuration_matches(
        context,
        recovery,
        {"id": "new-folder"},
    )
    assert _link_recovery_configuration_matches(
        context,
        {
            "spreadsheet_id": "new-sheet",
            "receipt_folder_id": "new-folder",
        },
        {"id": "new-folder"},
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
    assert workflow["receipts"][0]["content"] == b"failed"
    assert workflow["receipts"][1]["content"] == b""
    assert receipt_creation_counts(workflow) == (1, 1)


def test_preflight_failure_does_not_mark_upload_as_uncertain() -> None:
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [
            {
                "key": "preflight-failed",
                "original_name": "receipt.pdf",
                "content": b"receipt",
                "mime_type": "application/pdf",
                "linked": False,
            }
        ],
    )

    def upload(_item: Mapping[str, object]) -> Mapping[str, object]:
        raise GoogleDriveAccessError(
            "Drive inventory unavailable",
            retryable=True,
            upload_attempted=False,
        )

    process_receipt_recovery(
        workflow,
        upload_receipt=upload,
        link_receipt=lambda _reference: None,
    )

    assert workflow["receipts"][0].get("upload_uncertain") is not True


def test_uncertain_upload_reconciles_without_a_second_create() -> None:
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [
            {
                "key": "uncertain",
                "original_name": "receipt.pdf",
                "content": b"receipt",
                "mime_type": "application/pdf",
                "receipt_id": "a" * 32,
                "linked": False,
            }
        ],
    )
    upload_calls = 0
    reconcile_calls = 0

    def upload(_item: Mapping[str, object]) -> Mapping[str, object]:
        nonlocal upload_calls
        upload_calls += 1
        raise GoogleDriveAccessError(
            "Drive response was lost",
            retryable=True,
        )

    def reconcile(_item: Mapping[str, object]) -> Mapping[str, object] | None:
        nonlocal reconcile_calls
        reconcile_calls += 1
        if reconcile_calls == 1:
            return None
        return _drive_file("d", "receipt.pdf")

    process_receipt_recovery(
        workflow,
        upload_receipt=upload,
        reconcile_receipt=reconcile,
        link_receipt=lambda _reference: None,
    )
    assert upload_calls == 1
    assert receipt_creation_counts(workflow) == (0, 1)
    assert workflow["receipts"][0]["upload_uncertain"] is True

    process_receipt_recovery(
        workflow,
        upload_receipt=upload,
        reconcile_receipt=reconcile,
        link_receipt=lambda _reference: None,
    )

    assert upload_calls == 1
    assert reconcile_calls == 1
    assert receipt_creation_counts(workflow) == (0, 1)

    process_receipt_recovery(
        workflow,
        upload_receipt=upload,
        reconcile_receipt=reconcile,
        link_receipt=lambda _reference: None,
    )

    assert upload_calls == 1
    assert reconcile_calls == 2
    assert receipt_creation_counts(workflow) == (1, 0)
