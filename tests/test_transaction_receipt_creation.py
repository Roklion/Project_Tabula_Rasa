from __future__ import annotations

from collections.abc import Mapping
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import streamlit as st

from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.page_renderers.transactions.creation import render_add_transaction
from tabula_rasa.page_renderers.transactions.receipts import (
    UPLOADED_NOT_LINKED_MESSAGE,
    _cancel_editor_receipt_recovery,
    _fresh_transaction_receipt_count,
    _process_context_receipts,
    _record_editor_receipt_linked,
    clear_missing_editor_receipt_recoveries,
    clear_receipt_creation_recovery,
    handle_confirmed_transaction_receipts,
    new_receipt_creation_workflow,
    prepare_receipt_uploads,
    process_receipt_recovery,
    receipt_creation_counts,
    receipt_creation_workflow_key,
    receipt_editor_upload_reset_key,
    receipt_editor_workflow_key,
    render_receipts,
    render_receipt_creation_recovery,
)
from tabula_rasa.receipt_manifest import receipt_reference_from_drive_file


class UploadedFile:
    def __init__(self, name: str, content: bytes, mime_type: str) -> None:
        self.name = name
        self.type = mime_type
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


def _prepared(name: str = "receipt.pdf", content: bytes = b"receipt") -> dict:
    return prepare_receipt_uploads(
        [UploadedFile(name, content, "application/pdf")]
    )[0]


def _drive_file(receipt: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": f"drive-{receipt['receipt_id']}",
        "name": receipt["original_name"],
        "mimeType": receipt["mime_type"],
        "size": str(len(receipt["content"])),
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaReceiptId": receipt["receipt_id"],
            "tabulaRasaSha256": receipt["sha256"],
            "tabulaRasaOriginalName": receipt["original_name"],
        },
    }


def _context(
    *,
    profile: str = "north",
    spreadsheet: str = "north-sheet",
    folder: str = "north-folder",
    storage: object | None = None,
    drive: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        profile_key=profile,
        profile_secrets={
            "spreadsheet_id": spreadsheet,
            "google_drive": {"receipt_folder": {"id": folder}},
        },
        configuration_revision="revision",
        storage=storage or Mock(),
        get_drive_client=Mock(return_value=drive or Mock()),
        schedule_widget_reset=Mock(),
        reset_widget_state_if_requested=Mock(),
        mark_workbook_data_changed=Mock(),
    )


def test_prepare_receipts_keeps_stable_identity_and_content_hash() -> None:
    first, second = prepare_receipt_uploads(
        [
            UploadedFile("receipt.pdf", b"first", "application/pdf"),
            UploadedFile("receipt.pdf", b"second", "application/pdf"),
        ]
    )

    assert first["receipt_id"] != second["receipt_id"]
    assert first["sha256"] != second["sha256"]
    assert first["key"] != second["key"]
    assert first["content"] == b"first"


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


def test_prepare_receipts_rejects_count_and_batch_size_limits() -> None:
    upload = UploadedFile("receipt.pdf", b"123", "application/pdf")
    with pytest.raises(GoogleDriveAccessError, match="no more than 100"):
        prepare_receipt_uploads([upload, upload], existing_reference_count=99)
    with patch(
        "tabula_rasa.page_renderers.transactions.receipts.MAX_RECEIPT_UPLOAD_TOTAL_BYTES",
        5,
    ):
        with pytest.raises(GoogleDriveAccessError, match="200 MB total"):
            prepare_receipt_uploads([upload, upload])


def test_normal_upload_and_link_clears_pending_work() -> None:
    workflow = new_receipt_creation_workflow("txn-1", [_prepared()])
    linked = Mock()

    process_receipt_recovery(
        workflow,
        upload_receipt=_drive_file,
        link_receipt=linked,
    )

    assert receipt_creation_counts(workflow) == (1, 0)
    assert workflow["receipts"] == []
    assert linked.call_count == 1


def test_uploaded_but_unlinked_receipt_retries_reference_without_reupload() -> None:
    workflow = new_receipt_creation_workflow("txn-1", [_prepared()])
    upload = Mock(side_effect=_drive_file)
    link = Mock(side_effect=RuntimeError("Sheets unavailable"))

    process_receipt_recovery(
        workflow,
        upload_receipt=upload,
        link_receipt=link,
    )

    pending = workflow["receipts"][0]
    assert receipt_creation_counts(workflow) == (0, 1)
    assert pending["content"] == b""
    assert pending["reference"]["id"].startswith("drive-")
    assert UPLOADED_NOT_LINKED_MESSAGE in pending["error"]

    link.side_effect = None
    process_receipt_recovery(
        workflow,
        upload_receipt=upload,
        link_receipt=link,
    )

    assert receipt_creation_counts(workflow) == (1, 0)
    assert upload.call_count == 1


def test_uploaded_reference_retries_link_without_drive_access() -> None:
    pending = _prepared()
    pending["reference"] = _drive_file(pending)
    pending["content"] = b""
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [pending],
        spreadsheet_id="north-sheet",
        receipt_folder_id="north-folder",
    )
    storage = Mock()
    context = _context(storage=storage)
    context.get_drive_client.side_effect = GoogleDriveAccessError("Drive unavailable")

    _process_context_receipts(context, workflow, {"id": "north-folder"})

    context.get_drive_client.assert_not_called()
    storage.link_transaction_receipt.assert_called_once_with(
        "txn-1",
        reference=pending["reference"],
    )
    assert workflow["receipts"] == []


def test_one_upload_failure_does_not_stop_later_receipts() -> None:
    first = _prepared("first.pdf", b"first")
    second = _prepared("second.pdf", b"second")
    workflow = new_receipt_creation_workflow("txn-1", [first, second])

    def upload(receipt: Mapping[str, object]) -> Mapping[str, object]:
        if receipt["original_name"] == "first.pdf":
            raise GoogleDriveAccessError("Drive unavailable", retryable=True)
        return _drive_file(receipt)

    process_receipt_recovery(
        workflow,
        upload_receipt=upload,
        link_receipt=Mock(),
    )

    assert receipt_creation_counts(workflow) == (1, 1)
    assert workflow["receipts"][0]["original_name"] == "first.pdf"
    assert workflow["receipts"][0]["content"] == b"first"


def test_confirmed_receipts_use_selected_profile_and_clear_successful_state() -> None:
    storage = Mock()
    drive = Mock()
    drive.upload_receipt.side_effect = lambda **kwargs: _drive_file(
        {
            "receipt_id": kwargs["receipt_id"],
            "sha256": hashlib.sha256(kwargs["content"]).hexdigest(),
            "original_name": kwargs["original_name"],
            "mime_type": kwargs["mime_type"],
            "content": kwargs["content"],
        }
    )
    context = _context(storage=storage, drive=drive)
    state: dict[str, object] = {}

    with patch.object(st, "session_state", state):
        handle_confirmed_transaction_receipts(
            context,
            {"id": "txn-1"},
            [_prepared()],
        )

    context.get_drive_client.assert_called_once_with("north", "revision")
    drive.upload_receipt.assert_called_once()
    assert drive.upload_receipt.call_args.kwargs["folder_id"] == "north-folder"
    storage.link_transaction_receipt.assert_called_once()
    assert receipt_creation_workflow_key("north") not in state
    context.mark_workbook_data_changed.assert_called_once_with()


def test_creation_recovery_is_profile_scoped() -> None:
    north = new_receipt_creation_workflow(
        "north-txn",
        [_prepared()],
        spreadsheet_id="north-sheet",
        receipt_folder_id="north-folder",
    )
    south = new_receipt_creation_workflow(
        "south-txn",
        [_prepared()],
        spreadsheet_id="south-sheet",
        receipt_folder_id="south-folder",
    )
    state = {
        receipt_creation_workflow_key("north"): north,
        receipt_creation_workflow_key("south"): south,
    }
    context = _context(
        profile="south",
        spreadsheet="south-sheet",
        folder="south-folder",
    )

    with (
        patch.object(st, "session_state", state),
        patch.object(st, "info") as info,
        patch.object(st, "warning"),
        patch.object(st, "caption"),
        patch.object(st, "error"),
        patch.object(st, "button", return_value=False),
    ):
        assert render_receipt_creation_recovery(context)

    assert "south-txn" in info.call_args.args[0]
    assert state[receipt_creation_workflow_key("north")] is north
    assert state[receipt_creation_workflow_key("south")] is south


def test_creation_recovery_clears_when_saved_transaction_is_gone() -> None:
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [_prepared()],
        spreadsheet_id="north-sheet",
        receipt_folder_id="north-folder",
    )
    key = receipt_creation_workflow_key("north")
    state = {key: workflow}
    storage = Mock()
    storage.list_transactions.return_value = []
    context = _context(storage=storage)

    with (
        patch.object(st, "session_state", state),
        patch.object(st, "info"),
        patch.object(st, "warning") as warning,
        patch.object(st, "caption"),
        patch.object(st, "error"),
        patch.object(st, "button", return_value=True),
        patch.object(st, "rerun") as rerun,
    ):
        assert not render_receipt_creation_recovery(context)

    assert key not in state
    context.schedule_widget_reset.assert_called_once_with(
        "reset_add_transaction_form"
    )
    assert "no longer exists" in warning.call_args.args[0]
    rerun.assert_not_called()


def test_configuration_change_clears_only_matching_profile_workflow() -> None:
    north_key = receipt_editor_workflow_key("north", "txn-1")
    south_key = receipt_editor_workflow_key("south", "txn-2")
    state = {
        north_key: new_receipt_creation_workflow(
            "txn-1",
            [_prepared()],
            spreadsheet_id="old-sheet",
            receipt_folder_id="old-folder",
        ),
        south_key: new_receipt_creation_workflow(
            "txn-2",
            [_prepared()],
            spreadsheet_id="south-sheet",
            receipt_folder_id="south-folder",
        ),
    }

    context = _context()
    with patch.object(st, "session_state", state):
        notices = clear_missing_editor_receipt_recoveries(
            context,
            [{"id": "txn-1"}],
        )

    assert north_key not in state
    assert south_key in state
    assert len(notices) == 1
    assert "workflow was cleared" in notices[0]
    context.schedule_widget_reset.assert_called_once_with(
        receipt_editor_upload_reset_key("north", "txn-1")
    )


def test_missing_transaction_clears_recovery_without_deleting_drive_file() -> None:
    key = receipt_editor_workflow_key("north", "txn-1")
    state = {
        key: new_receipt_creation_workflow(
            "txn-1",
            [_prepared()],
            spreadsheet_id="north-sheet",
            receipt_folder_id="north-folder",
        )
    }

    context = _context()
    with patch.object(st, "session_state", state):
        notices = clear_missing_editor_receipt_recoveries(context, [])

    assert key not in state
    assert "remain in Google Drive" in notices[0]
    context.schedule_widget_reset.assert_called_once_with(
        receipt_editor_upload_reset_key("north", "txn-1")
    )


def test_manual_unreferenced_link_finishes_matching_editor_workflow() -> None:
    pending = _prepared()
    pending["reference"] = _drive_file(pending)
    pending["content"] = b""
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [pending],
        spreadsheet_id="north-sheet",
        receipt_folder_id="north-folder",
    )
    state = {receipt_editor_workflow_key("north", "txn-1"): workflow}
    context = _context()

    with patch.object(st, "session_state", state):
        _record_editor_receipt_linked(
            context,
            "txn-1",
            {"id": pending["reference"]["id"]},
        )

    assert receipt_editor_workflow_key("north", "txn-1") not in state
    context.schedule_widget_reset.assert_called_once()


def test_manual_unreferenced_link_reports_success_when_recovery_finishes() -> None:
    pending = _prepared()
    drive_file = _drive_file(pending)
    pending["reference"] = drive_file
    pending["content"] = b""
    workflow = new_receipt_creation_workflow(
        "txn-1",
        [pending],
        spreadsheet_id="north-sheet",
        receipt_folder_id="north-folder",
    )
    workflow_key = receipt_editor_workflow_key("north", "txn-1")
    notice_key = "receipt-notice-north-txn-1"
    state = {workflow_key: workflow}
    storage = Mock()
    drive = Mock()
    drive.list_profile_receipts.return_value = [drive_file]
    context = _context(storage=storage, drive=drive)

    with (
        patch.object(st, "session_state", state),
        patch.object(st, "divider"),
        patch.object(st, "subheader"),
        patch.object(st, "warning"),
        patch.object(st, "caption"),
        patch.object(st, "error"),
        patch.object(st, "empty", return_value=Mock()),
        patch.object(st, "selectbox", return_value=drive_file["id"]),
        patch.object(
            st,
            "button",
            side_effect=lambda label, **_kwargs: label == "Link selected receipt",
        ),
        patch.object(st, "rerun") as rerun,
    ):
        render_receipts(
            context,
            selected={"receipt_references": ""},
            all_transactions=[],
            edit_id="txn-1",
        )

    storage.link_transaction_receipt.assert_called_once_with(
        "txn-1",
        reference=receipt_reference_from_drive_file(drive_file),
    )
    assert workflow_key not in state
    assert state[notice_key] == f"Receipt linked: {drive_file['name']}"
    rerun.assert_called_once_with()


def test_render_receipts_accepts_one_custom_mixed_use_section_heading() -> None:
    context = _context(storage=Mock(), drive=Mock())
    context.get_drive_client.return_value.list_profile_receipts.return_value = []
    with (
        patch.object(st, "session_state", {}),
        patch.object(st, "divider"),
        patch.object(st, "subheader") as subheader,
        patch.object(st, "caption") as caption,
        patch.object(st, "info"),
        patch.object(st, "warning"),
        patch.object(st, "error"),
    ):
        render_receipts(
            context,
            selected={"receipt_references": ""},
            all_transactions=[],
            edit_id="source-1",
            section_title="Receipts",
            section_caption="Manage receipts here; the linked ledger projection is read-only.",
        )

    subheader.assert_called_once_with("Receipts")
    caption.assert_any_call(
        "Manage receipts here; the linked ledger projection is read-only."
    )


def test_cancel_and_delete_cleanup_are_profile_and_target_scoped() -> None:
    north_key = receipt_editor_workflow_key("north", "txn-1")
    south_key = receipt_editor_workflow_key("south", "txn-1")
    state = {
        north_key: new_receipt_creation_workflow("txn-1", [_prepared()]),
        south_key: new_receipt_creation_workflow("txn-1", [_prepared()]),
        receipt_creation_workflow_key("north"): new_receipt_creation_workflow(
            "txn-2", [_prepared()]
        ),
    }
    context = _context()

    with patch.object(st, "session_state", state):
        _cancel_editor_receipt_recovery(context, "txn-1")
        clear_receipt_creation_recovery(context, "txn-1")

    assert north_key not in state
    assert south_key in state
    assert receipt_creation_workflow_key("north") in state


def test_fresh_receipt_count_uses_forced_sheets_read() -> None:
    storage = Mock()
    storage.list_transactions.return_value = [
        {
            "id": "txn-1",
            "receipt_references": '[{"id":"drive123456","name":"one.pdf"}]',
        }
    ]

    assert _fresh_transaction_receipt_count(
        _context(storage=storage),
        "txn-1",
    ) == 1
    storage.list_transactions.assert_called_once_with(_force_refresh=True)


def test_mixed_use_creation_recovery_is_not_rendered_by_add_transaction() -> None:
    workflow = new_receipt_creation_workflow(
        "projection-1",
        [_prepared()],
        mixed_use_source_id="source-1",
    )
    state = {receipt_creation_workflow_key("north"): workflow}

    with (
        patch.object(st, "session_state", state),
        patch(
            "tabula_rasa.page_renderers.transactions.creation.render_receipt_creation_recovery"
        ) as render_recovery,
    ):
        render_add_transaction(
            SimpleNamespace(profile_key="north"),
            account_map={},
            categories=[],
            category_paths={},
            payees=[],
            tags=[],
        )

    render_recovery.assert_not_called()
