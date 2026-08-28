from __future__ import annotations

from collections.abc import Mapping
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import streamlit as st

from tabula_rasa.google_drive import GoogleDriveAccessError, GoogleDriveError
from tabula_rasa.page_renderers.transactions.receipts import (
    EDITOR_RECEIPT_TRANSACTION_MISSING_NOTICE,
    handle_confirmed_transaction_receipts,
    clear_receipt_creation_recovery,
    clear_missing_editor_receipt_recoveries,
    editor_receipt_recovery_active,
    new_receipt_creation_workflow,
    prepare_receipt_uploads,
    process_receipt_recovery,
    receipt_creation_counts,
    receipt_creation_workflow_key,
    receipt_editor_notice_key,
    render_receipt_creation_recovery,
    _workflow_configuration_matches,
    _link_recovery_configuration_matches,
    _workflow_has_uploaded_receipt,
    _transaction_still_exists,
    _fresh_transaction_receipt_count,
    _new_unresolved_receipt_count,
    _reconcile_editor_workflow_references,
    _discard_editor_workflow_receipt,
    _cancel_editor_receipt_recovery,
    _finish_editor_receipt_workflow,
    _render_editor_receipt_recovery,
    _process_editor_receipts,
    _record_editor_receipt_linked,
    _start_editor_receipt_workflow,
    receipt_editor_workflow_key,
)
from tabula_rasa.receipt_manifest import receipt_reference_from_drive_file
from tabula_rasa.storage import StorageError


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


def test_prepare_receipts_rejects_batches_over_aggregate_memory_limit() -> None:
    with patch(
        "tabula_rasa.page_renderers.transactions.receipts.MAX_RECEIPT_UPLOAD_TOTAL_BYTES",
        5,
    ):
        with pytest.raises(GoogleDriveAccessError, match="200 MB total"):
            prepare_receipt_uploads(
                [
                    UploadedFile("first.pdf", b"123", "application/pdf"),
                    UploadedFile("second.pdf", b"456", "application/pdf"),
                ]
            )


def test_editor_receipt_selection_respects_existing_manifest_capacity() -> None:
    uploaded = UploadedFile("receipt.pdf", b"receipt", "application/pdf")

    with pytest.raises(GoogleDriveAccessError, match="no more than 100"):
        prepare_receipt_uploads(
            [uploaded, uploaded],
            existing_reference_count=99,
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
    session_state[receipt_editor_workflow_key("north", "north-txn")] = (
        new_receipt_creation_workflow("north-txn", [], profile_key="north")
    )
    session_state["receipt-editor-notice-north-north-txn"] = "stale notice"
    with patch.object(st, "session_state", session_state):
        clear_receipt_creation_recovery(north_context, "other-txn")
        assert receipt_creation_workflow_key("north") in session_state
        clear_receipt_creation_recovery(north_context, "north-txn")

    assert receipt_creation_workflow_key("north") not in session_state
    assert receipt_editor_workflow_key("north", "north-txn") not in session_state
    assert "receipt-editor-notice-north-north-txn" not in session_state


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


def test_editor_capacity_rechecks_fresh_sheets_data() -> None:
    references = [
        {
            "id": f"drive-receipt-{index:02d}",
            "name": f"receipt-{index}.pdf",
            "receipt_id": f"{index:032d}",
            "original_filename": f"receipt-{index}.pdf",
            "mime_type": "application/pdf",
            "byte_size": 7,
            "sha256": "a" * 64,
        }
        for index in range(99)
    ]
    storage = SimpleNamespace(
        list_transactions=lambda **kwargs: (
            assert_force_refresh(kwargs),
            [{"id": "txn-1", "receipt_references": json.dumps(references)}],
        )[1]
    )
    context = SimpleNamespace(storage=storage)

    assert _fresh_transaction_receipt_count(context, "txn-1") == 99


def test_editor_retry_rejects_batch_over_fresh_capacity() -> None:
    references = [
        {"id": f"drive-{index:08d}", "name": f"receipt-{index}.pdf"}
        for index in range(100)
    ]
    storage = SimpleNamespace(
        list_transactions=lambda **kwargs: (
            assert_force_refresh(kwargs),
            [{"id": "txn-1", "receipt_references": json.dumps(references)}],
        )[1]
    )
    context = SimpleNamespace(
        profile_key="north",
        storage=storage,
        profile_secrets={"spreadsheet_id": "sheet"},
        configuration_revision="revision",
        get_drive_client=lambda *_args: (_ for _ in ()).throw(
            AssertionError("Drive processing must not start at capacity")
        ),
    )
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [{"key": "receipt", "original_name": "receipt.pdf", "content": b"receipt"}],
        profile_key="north",
        spreadsheet_id="sheet",
        receipt_folder_id="folder",
    )
    session_state = {receipt_editor_workflow_key("north", "txn-1"): workflow}

    with (
        patch.object(st, "session_state", session_state),
        patch.object(st, "warning"),
        patch.object(st, "caption"),
        patch.object(st, "empty", return_value=Mock()),
        patch.object(st, "button", side_effect=[True, False]),
        patch.object(st, "rerun", side_effect=RuntimeError("rerun")),
    ):
        with pytest.raises(RuntimeError, match="rerun"):
            _render_editor_receipt_recovery(context, "txn-1", {"id": "folder"})

    assert workflow["configuration_error"]
    assert "no more than 100" in workflow["configuration_error"]


def test_editor_retry_does_not_count_a_reference_already_in_sheets() -> None:
    existing_file_id = "drive-existing"

    assert _new_unresolved_receipt_count(
        [
            {"reference": {"id": existing_file_id}},
            {"drive_file": {"id": "drive-new"}},
            {"content": b"not-uploaded"},
        ],
        {existing_file_id},
    ) == 2


def test_editor_retry_reconciles_receipts_removed_from_sheets() -> None:
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [
            {"linked": True, "reference": {"id": "drive-removed"}},
            {"linked": True, "reference": {"id": "drive-kept"}},
            {"linked": False, "reference": {"id": "drive-pending"}},
        ],
    )

    _reconcile_editor_workflow_references(
        workflow,
        [{"id": "drive-kept"}, {"id": "drive-pending"}],
    )

    assert [
        receipt["reference"]["id"]
        for receipt in workflow["receipts"]
    ] == ["drive-kept", "drive-pending"]


def test_editor_retry_persists_deleted_transaction_notice() -> None:
    storage = SimpleNamespace(
        list_transactions=lambda **kwargs: (
            assert_force_refresh(kwargs),
            [],
        )[1]
    )
    context = SimpleNamespace(
        profile_key="north",
        storage=storage,
        profile_secrets={"spreadsheet_id": "sheet"},
        configuration_revision="revision",
    )
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [{"key": "receipt", "original_name": "receipt.pdf", "content": b"receipt"}],
        profile_key="north",
        spreadsheet_id="sheet",
        receipt_folder_id="folder",
    )
    session_state = {receipt_editor_workflow_key("north", "txn-1"): workflow}

    with (
        patch.object(st, "session_state", session_state),
        patch.object(st, "warning"),
        patch.object(st, "caption"),
        patch.object(st, "empty", return_value=Mock()),
        patch.object(st, "button", side_effect=[True, False]),
        patch.object(st, "rerun", side_effect=RuntimeError("rerun")),
    ):
        with pytest.raises(RuntimeError, match="rerun"):
            _render_editor_receipt_recovery(context, "txn-1", {"id": "folder"})

    assert receipt_editor_workflow_key("north", "txn-1") not in session_state
    assert session_state[receipt_editor_notice_key("north", "txn-1")] == {
        "message": EDITOR_RECEIPT_TRANSACTION_MISSING_NOTICE,
        "spreadsheet_id": "sheet",
        "receipt_folder_id": "folder",
        "validated_configuration": "sheet\x00",
    }


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


def test_editor_receipt_recovery_cancel_discards_workflow() -> None:
    context = SimpleNamespace(profile_key="north")
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [{"key": "receipt", "original_name": "receipt.pdf", "content": b"receipt"}],
        profile_key="north",
    )
    session_state = {receipt_editor_workflow_key("north", "txn-1"): workflow}

    with (
        patch.object(st, "session_state", session_state),
        patch.object(st, "warning"),
        patch.object(st, "caption"),
        patch.object(st, "button", side_effect=[False, True]),
        patch.object(st, "rerun", side_effect=RuntimeError("rerun")),
    ):
        with pytest.raises(RuntimeError, match="rerun"):
            _render_editor_receipt_recovery(context, "txn-1", {"id": "folder"})

    assert receipt_editor_workflow_key("north", "txn-1") not in session_state
    assert session_state[receipt_editor_notice_key("north", "txn-1")] == {
        "message": (
            "Receipt recovery canceled. Files already uploaded remain in Google "
            "Drive and can be linked from the Unreferenced receipt workflow."
        ),
        "spreadsheet_id": "",
        "receipt_folder_id": "",
        "validated_configuration": "",
    }


def test_cancel_editor_receipt_recovery_is_profile_scoped() -> None:
    north_workflow = new_receipt_creation_workflow(
        "txn-1", [], profile_key="north"
    )
    south_workflow = new_receipt_creation_workflow(
        "txn-1", [], profile_key="south"
    )
    session_state = {
        receipt_editor_workflow_key("north", "txn-1"): north_workflow,
        receipt_editor_workflow_key("south", "txn-1"): south_workflow,
    }

    with patch.object(st, "session_state", session_state):
        _cancel_editor_receipt_recovery(
            SimpleNamespace(profile_key="north"),
            "txn-1",
        )

    assert receipt_editor_workflow_key("north", "txn-1") not in session_state
    assert receipt_editor_workflow_key("south", "txn-1") in session_state


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


def test_editor_receipt_recovery_retries_only_unresolved_without_reupload() -> None:
    upload_calls: list[str] = []
    link_calls: list[str] = []
    fail_upload = {"value": True}
    fail_link = {"value": True}

    class DriveClient:
        def upload_receipt(self, **kwargs: object) -> Mapping[str, object]:
            name = str(kwargs["original_name"])
            upload_calls.append(name)
            content = bytes(kwargs["content"])
            if content == b"second" and fail_upload["value"]:
                raise RuntimeError("second upload failed")
            return _drive_file(
                "a" if content == b"first" else "c",
                name,
            )

    class StorageClient:
        def link_transaction_receipt(
            self,
            _transaction_id: str,
            *,
            reference: Mapping[str, object],
        ) -> None:
            receipt_id = str(reference["receipt_id"])
            link_calls.append(receipt_id)
            if receipt_id.startswith("c") and fail_link["value"]:
                raise RuntimeError("second link failed")

    context = SimpleNamespace(
        profile_key="north",
        storage=StorageClient(),
        profile_secrets={
            "spreadsheet_id": "north-sheet",
            "google_drive": {"receipt_folder": {"id": "north-folder"}},
        },
        configuration_revision="revision",
        get_drive_client=lambda *_args: DriveClient(),
        mark_workbook_data_changed=Mock(),
    )
    receipts = prepare_receipt_uploads(
        [
            UploadedFile("receipt.pdf", b"first", "application/pdf"),
            UploadedFile("receipt.pdf", b"second", "application/pdf"),
        ]
    )
    session_state: dict[str, object] = {}

    with patch.object(st, "session_state", session_state):
        workflow = _start_editor_receipt_workflow(
            context,
            "txn-1",
            receipts,
            {"id": "north-folder"},
        )
        assert receipt_creation_counts(workflow) == (1, 1)
        assert upload_calls == ["receipt.pdf", "receipt.pdf"]

        fail_upload["value"] = False
        _process_editor_receipts(context, workflow, {"id": "north-folder"})
        assert receipt_creation_counts(workflow) == (1, 1)
        assert upload_calls == ["receipt.pdf", "receipt.pdf", "receipt.pdf"]
        assert isinstance(workflow["receipts"][1]["reference"], Mapping)

        fail_link["value"] = False
        _process_editor_receipts(context, workflow, {"id": "north-folder"})
        assert receipt_creation_counts(workflow) == (2, 0)
        assert upload_calls == ["receipt.pdf", "receipt.pdf", "receipt.pdf"]
        assert len(link_calls) == 3
        assert _finish_editor_receipt_workflow(context, "txn-1", workflow)

    assert receipt_editor_workflow_key("north", "txn-1") not in session_state
    assert session_state[receipt_editor_notice_key("north", "txn-1")] == {
        "message": "2 receipt(s) uploaded and linked; 0 unresolved.",
        "spreadsheet_id": "north-sheet",
        "receipt_folder_id": "north-folder",
        "validated_configuration": "",
    }


def test_editor_receipt_recovery_forgets_receipt_after_manual_unlink() -> None:
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [
            {"linked": True, "reference": {"id": "drive-removed"}},
            {"linked": False, "reference": {"id": "drive-pending"}},
        ],
    )

    _discard_editor_workflow_receipt(workflow, "drive-removed")

    assert workflow["receipts"] == [
        {"linked": False, "reference": {"id": "drive-pending"}}
    ]


def test_editor_receipt_workflow_persists_drive_configuration_error() -> None:
    context = SimpleNamespace(
        profile_key="north",
        configuration_revision="revision",
        profile_secrets={"spreadsheet_id": "north-sheet"},
        get_drive_client=Mock(
            side_effect=GoogleDriveError("Drive is unavailable")
        ),
    )
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [{"linked": False, "content": b"receipt"}],
    )
    session_state: dict[str, object] = {}

    with patch.object(st, "session_state", session_state):
        result = _start_editor_receipt_workflow(
            context,
            "txn-1",
            workflow["receipts"],
            {"id": "north-folder"},
        )

    assert result["configuration_error"] == "Drive is unavailable"
    assert session_state[receipt_editor_workflow_key("north", "txn-1")] is result


def test_editor_manual_link_recovery_check_can_finish_after_read_failure() -> None:
    reference = {"id": "drive-receipt", "name": "receipt.pdf"}
    read_count = 0

    def list_transactions(**_kwargs: object) -> list[dict[str, object]]:
        nonlocal read_count
        read_count += 1
        if read_count == 1:
            raise StorageError("temporary Sheets read failure")
        return [{"id": "txn-1", "receipt_references": json.dumps([reference])}]

    context = SimpleNamespace(
        profile_key="north",
        storage=SimpleNamespace(list_transactions=list_transactions),
        profile_secrets={
            "spreadsheet_id": "north-sheet",
            "google_drive": {"receipt_folder": {"id": "north-folder"}},
        },
        configuration_revision="revision",
        get_drive_client=Mock(
            side_effect=AssertionError("No Drive work is needed after linking")
        ),
    )
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [{"linked": False, "reference": reference, "content": b""}],
        profile_key="north",
        spreadsheet_id="north-sheet",
        receipt_folder_id="north-folder",
    )
    session_state = {receipt_editor_workflow_key("north", "txn-1"): workflow}

    with patch.object(st, "session_state", session_state):
        assert not _record_editor_receipt_linked(context, "txn-1", reference)
        with (
            patch.object(st, "error"),
            patch.object(st, "button", return_value=True),
            patch.object(st, "rerun", side_effect=RuntimeError("rerun")),
        ):
            with pytest.raises(RuntimeError, match="rerun"):
                _render_editor_receipt_recovery(
                    context,
                    "txn-1",
                    {"id": "north-folder"},
                )

    assert read_count == 2
    assert receipt_editor_workflow_key("north", "txn-1") not in session_state
    assert session_state[receipt_editor_notice_key("north", "txn-1")] == {
        "message": "1 receipt(s) uploaded and linked; 0 unresolved.",
        "spreadsheet_id": "north-sheet",
        "receipt_folder_id": "north-folder",
        "validated_configuration": "",
    }


def test_editor_receipt_recovery_isolated_by_profile() -> None:
    drive_profiles: list[str] = []

    class DriveClient:
        def upload_receipt(self, **kwargs: object) -> Mapping[str, object]:
            drive_profiles.append(str(kwargs["profile_key"]))
            return _drive_file("a", f"{kwargs['profile_key']}.pdf")

    class StorageClient:
        def link_transaction_receipt(
            self,
            _transaction_id: str,
            *,
            reference: Mapping[str, object],
        ) -> None:
            del reference

    def context_for(profile_key: str) -> SimpleNamespace:
        return SimpleNamespace(
            profile_key=profile_key,
            storage=StorageClient(),
            profile_secrets={
                "spreadsheet_id": f"{profile_key}-sheet",
                "google_drive": {
                    "receipt_folder": {"id": f"{profile_key}-folder"}
                },
            },
            configuration_revision="revision",
            get_drive_client=lambda *_args: DriveClient(),
            mark_workbook_data_changed=Mock(),
        )

    session_state: dict[str, object] = {}
    with patch.object(st, "session_state", session_state):
        for profile_key in ("north", "south"):
            context = context_for(profile_key)
            receipt = prepare_receipt_uploads(
                [UploadedFile("receipt.pdf", b"receipt", "application/pdf")]
            )
            workflow = _start_editor_receipt_workflow(
                context,
                "shared-transaction-id",
                receipt,
                {"id": f"{profile_key}-folder"},
            )
            assert receipt_creation_counts(workflow) == (1, 0)

    assert drive_profiles == ["north", "south"]
    assert (
        session_state[
            receipt_editor_workflow_key("north", "shared-transaction-id")
        ]["profile_key"]
        == "north"
    )
    assert (
        session_state[
            receipt_editor_workflow_key("south", "shared-transaction-id")
        ]["profile_key"]
        == "south"
    )


def test_unreferenced_link_resolves_matching_editor_recovery() -> None:
    first_reference = receipt_reference_from_drive_file(_drive_file("a", "first.pdf"))
    second_reference = receipt_reference_from_drive_file(_drive_file("b", "second.pdf"))
    context = SimpleNamespace(
        profile_key="north",
        schedule_widget_reset=Mock(),
        storage=SimpleNamespace(
            list_transactions=lambda **_kwargs: [
                {
                    "id": "txn-1",
                    "receipt_references": [first_reference, second_reference],
                }
            ]
        ),
    )
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [
            {
                "linked": False,
                "reference": first_reference,
                "content": b"",
                "error": "link failed",
            },
            {
                "linked": False,
                "reference": second_reference,
                "content": b"",
                "error": "link failed",
            },
        ],
        profile_key="north",
    )
    session_state: dict[str, object] = {
        receipt_editor_workflow_key("north", "txn-1"): workflow,
    }

    with patch.object(st, "session_state", session_state):
        assert not _record_editor_receipt_linked(
            context,
            "txn-1",
            first_reference,
        )
        assert receipt_creation_counts(workflow) == (1, 1)
        assert _record_editor_receipt_linked(
            context,
            "txn-1",
            second_reference,
        )

    assert receipt_editor_workflow_key("north", "txn-1") not in session_state
    assert session_state[receipt_editor_notice_key("north", "txn-1")] == {
        "message": "2 receipt(s) uploaded and linked; 0 unresolved.",
        "spreadsheet_id": "",
        "receipt_folder_id": "",
        "validated_configuration": "",
    }


def test_missing_editor_recovery_cleanup_is_profile_scoped() -> None:
    north_workflow = new_receipt_creation_workflow(
        "north-gone", [], profile_key="north"
    )
    south_workflow = new_receipt_creation_workflow(
        "south-gone", [], profile_key="south"
    )
    session_state: dict[str, object] = {
        receipt_editor_workflow_key("north", "north-gone"): north_workflow,
        receipt_editor_workflow_key("south", "south-gone"): south_workflow,
    }
    with patch.object(st, "session_state", session_state):
        notices = clear_missing_editor_receipt_recoveries(
            SimpleNamespace(profile_key="north", profile_secrets={}),
            [{"id": "north-still-present"}],
        )

    assert notices == [
        "The transaction no longer exists. Uploaded files remain in Google "
        "Drive and can be linked from the Unreferenced receipt workflow."
    ]
    assert receipt_editor_workflow_key("north", "north-gone") not in session_state
    assert receipt_editor_workflow_key("south", "south-gone") in session_state
    assert session_state[
        receipt_editor_notice_key("north", "north-gone")
    ] == {
        "message": EDITOR_RECEIPT_TRANSACTION_MISSING_NOTICE,
        "spreadsheet_id": "",
        "receipt_folder_id": "",
        "validated_configuration": "\x00",
    }


def test_editor_receipt_recovery_active_is_profile_scoped() -> None:
    session_state: dict[str, object] = {
        receipt_editor_workflow_key("north", "txn-1"): {},
        receipt_editor_workflow_key("south", "txn-2"): {},
        "receipt-editor-notice-north-deleted": "notice",
    }
    with patch.object(st, "session_state", session_state):
        assert editor_receipt_recovery_active(SimpleNamespace(profile_key="north"))
        assert editor_receipt_recovery_active(SimpleNamespace(profile_key="south"))
        assert not editor_receipt_recovery_active(SimpleNamespace(profile_key="west"))


def test_editor_receipt_recovery_active_ignores_validated_notice() -> None:
    session_state: dict[str, object] = {
        receipt_editor_notice_key("north", "txn-1"): {
            "message": "Receipt recovery complete.",
            "spreadsheet_id": "",
            "receipt_folder_id": "",
            "validated_configuration": "\x00",
        }
    }

    with patch.object(st, "session_state", session_state):
        assert not editor_receipt_recovery_active(
            SimpleNamespace(profile_key="north", profile_secrets={})
        )


def test_missing_editor_recovery_is_preserved_after_profile_reconfiguration() -> None:
    workflow = new_receipt_creation_workflow(
        "old-txn",
        [],
        profile_key="north",
        spreadsheet_id="old-sheet",
    )
    session_state: dict[str, object] = {
        receipt_editor_workflow_key("north", "old-txn"): workflow,
    }
    with patch.object(st, "session_state", session_state):
        notices = clear_missing_editor_receipt_recoveries(
            SimpleNamespace(
                profile_key="north",
                profile_secrets={"spreadsheet_id": "new-sheet"},
            ),
            [],
        )

    assert notices == []
    assert receipt_editor_workflow_key("north", "old-txn") in session_state


def test_missing_editor_recovery_cleanup_pops_orphaned_notice() -> None:
    notice = "The transaction no longer exists. Uploaded files remain in Drive."
    session_state: dict[str, object] = {
        "receipt-editor-notice-north-north-gone": notice,
        "receipt-editor-notice-south-south-gone": "Keep south notice",
    }

    with patch.object(st, "session_state", session_state):
        notices = clear_missing_editor_receipt_recoveries(
            SimpleNamespace(profile_key="north", profile_secrets={}),
            [{"id": "north-still-present"}],
        )

    assert notices == [EDITOR_RECEIPT_TRANSACTION_MISSING_NOTICE]
    assert "receipt-editor-notice-north-north-gone" not in session_state
    assert session_state["receipt-editor-notice-south-south-gone"] == (
        "Keep south notice"
    )


def test_missing_editor_recovery_replaces_orphaned_success_notice() -> None:
    key = "receipt-editor-notice-north-north-gone"
    session_state: dict[str, object] = {
        key: "2 receipt(s) uploaded and linked; 0 unresolved."
    }

    with patch.object(st, "session_state", session_state):
        notices = clear_missing_editor_receipt_recoveries(
            SimpleNamespace(profile_key="north", profile_secrets={}),
            [],
        )

    assert notices == [EDITOR_RECEIPT_TRANSACTION_MISSING_NOTICE]
    assert key not in session_state


def test_missing_editor_recovery_preserves_notice_after_profile_reconfiguration() -> None:
    key = receipt_editor_notice_key("north", "old-txn")
    session_state: dict[str, object] = {
        key: {
            "message": "2 receipt(s) uploaded and linked; 0 unresolved.",
            "spreadsheet_id": "old-sheet",
            "receipt_folder_id": "old-folder",
            "validated_configuration": "",
        }
    }

    with patch.object(st, "session_state", session_state):
        notices = clear_missing_editor_receipt_recoveries(
            SimpleNamespace(
                profile_key="north",
                profile_secrets={"spreadsheet_id": "new-sheet"},
            ),
            [],
        )

    assert notices == []
    notice = session_state[key]
    assert isinstance(notice, Mapping)
    assert notice["message"] == "2 receipt(s) uploaded and linked; 0 unresolved."


def test_missing_editor_recovery_is_preserved_after_receipt_folder_change() -> None:
    workflow = new_receipt_creation_workflow(
        "old-txn",
        [],
        profile_key="north",
        spreadsheet_id="north-sheet",
        receipt_folder_id="old-folder",
    )
    session_state: dict[str, object] = {
        receipt_editor_workflow_key("north", "old-txn"): workflow,
    }

    with patch.object(st, "session_state", session_state):
        notices = clear_missing_editor_receipt_recoveries(
            SimpleNamespace(
                profile_key="north",
                profile_secrets={
                    "spreadsheet_id": "north-sheet",
                    "google_drive": {
                        "receipt_folder": {"id": "new-folder"}
                    },
                },
            ),
            [],
        )

    assert notices == []
    assert receipt_editor_workflow_key("north", "old-txn") in session_state
