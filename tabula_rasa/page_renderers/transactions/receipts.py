"""Receipt management for an existing transaction."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Mapping, Sequence
from typing import Any, Callable, MutableMapping

import streamlit as st

from tabula_rasa.google_drive import (
    GoogleDriveAccessError,
    GoogleDriveError,
    validate_receipt_upload,
)
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.receipt_manifest import (
    MAX_RECEIPT_REFERENCES,
    ReceiptManifestError,
    receipt_reference_from_drive_file,
)
from tabula_rasa.storage import StorageError, decode_receipt_references


RECEIPT_UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "webp", "heic"]
RECEIPT_CREATION_WORKFLOW_KEY = "transaction_receipt_creation_workflow"
RECEIPT_EDITOR_WORKFLOW_KEY = "transaction_receipt_editor_workflow"
MAX_RECEIPT_UPLOAD_TOTAL_BYTES = 200 * 1024 * 1024
EDITOR_RECEIPT_TRANSACTION_MISSING_NOTICE = (
    "The transaction no longer exists. Uploaded files remain in Google Drive "
    "and can be linked from the Unreferenced receipt workflow."
)
EDITOR_RECEIPT_RECOVERY_CANCELED_NOTICE = (
    "Receipt recovery canceled. Files already uploaded remain in Google Drive "
    "and can be linked from the Unreferenced receipt workflow."
)


def receipt_creation_workflow_key(profile_key: str) -> str:
    """Return the session key for one profile's in-progress recovery."""
    return f"{RECEIPT_CREATION_WORKFLOW_KEY}:{profile_key}"


def receipt_editor_workflow_key(profile_key: str, transaction_id: str) -> str:
    """Return the session key for one profile's editor recovery."""
    return f"{RECEIPT_EDITOR_WORKFLOW_KEY}:{len(profile_key)}:{profile_key}:{transaction_id}"


def receipt_editor_workflow_key_prefix(profile_key: str) -> str:
    """Return the unambiguous session-key prefix for one profile's recovery."""
    return f"{RECEIPT_EDITOR_WORKFLOW_KEY}:{len(profile_key)}:{profile_key}:"


def receipt_editor_notice_key(profile_key: str, transaction_id: str) -> str:
    """Return the session key for one profile's editor notice."""
    return f"receipt-editor-notice:{len(profile_key)}:{profile_key}:{transaction_id}"


def receipt_editor_notice_key_prefix(profile_key: str) -> str:
    """Return the unambiguous session-key prefix for one profile's notices."""
    return f"receipt-editor-notice:{len(profile_key)}:{profile_key}:"


def receipt_editor_upload_reset_key(profile_key: str, transaction_id: str) -> str:
    """Return the one-shot reset flag for a completed editor upload."""
    return f"reset-receipt-editor:{profile_key}:{transaction_id}"


def prepare_receipt_uploads(
    uploaded_files: Sequence[Any],
    *,
    existing_reference_count: int = 0,
) -> list[dict[str, Any]]:
    """Copy and validate every selected file before the Sheets write."""
    if existing_reference_count < 0:
        raise ValueError("Existing receipt reference count cannot be negative")
    if existing_reference_count + len(uploaded_files) > MAX_RECEIPT_REFERENCES:
        raise GoogleDriveAccessError(
            "A transaction can reference no more than 100 receipts. "
            "Remove an existing receipt reference or select fewer files."
        )
    prepared: list[dict[str, Any]] = []
    total_bytes = 0
    for index, uploaded_file in enumerate(uploaded_files):
        name = str(getattr(uploaded_file, "name", "") or "")
        content = uploaded_file.getvalue()
        total_bytes += len(content)
        if total_bytes > MAX_RECEIPT_UPLOAD_TOTAL_BYTES:
            raise GoogleDriveAccessError(
                "Selected receipt files cannot exceed 200 MB total. "
                "Select fewer or smaller files."
            )
        validate_receipt_upload(name, content)
        prepared.append(
            {
                "key": f"{index}:{hashlib.sha256(content).hexdigest()}",
                "receipt_id": secrets.token_hex(16),
                "original_name": name,
                "mime_type": str(
                    getattr(uploaded_file, "type", "")
                    or "application/octet-stream"
                ),
                "content": content,
                "linked": False,
                "reference": None,
                "drive_file": None,
                "error": "",
            }
        )
    return prepared


def new_receipt_creation_workflow(
    transaction_id: str,
    receipts: Sequence[Mapping[str, Any]],
    *,
    profile_key: str = "",
    configuration_revision: str = "",
    spreadsheet_id: str = "",
    receipt_folder_id: str = "",
) -> dict[str, Any]:
    """Create session-only recovery state after a confirmed Sheets write."""
    return {
        "profile_key": profile_key,
        "transaction_id": transaction_id,
        "configuration_revision": configuration_revision,
        "spreadsheet_id": spreadsheet_id,
        "receipt_folder_id": receipt_folder_id,
        "receipts": [dict(receipt) for receipt in receipts],
    }


def process_receipt_recovery(
    workflow: MutableMapping[str, Any],
    *,
    upload_receipt: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    reconcile_receipt: Callable[
        [Mapping[str, Any]], Mapping[str, Any] | None
    ] | None = None,
    link_receipt: Callable[[Mapping[str, Any]], object],
) -> None:
    """Upload and link unresolved receipts, retaining only retry pointers."""
    for receipt in workflow.get("receipts", []):
        if not isinstance(receipt, MutableMapping):
            continue
        receipt.setdefault("receipt_id", secrets.token_hex(16))
        if receipt.get("linked") is True:
            continue
        reference = receipt.get("reference")
        if not isinstance(reference, Mapping) and isinstance(
            receipt.get("drive_file"), Mapping
        ):
            try:
                reference = receipt_reference_from_drive_file(receipt["drive_file"])
            except Exception as error:  # noqa: BLE001 - preserve Drive recovery pointer
                receipt["error"] = (
                    "The Drive file was uploaded, but its receipt metadata "
                    f"could not be read: {error}"
                )
                continue
            receipt["reference"] = reference
        if not isinstance(reference, Mapping):
            if receipt.get("upload_uncertain") is True and reconcile_receipt:
                try:
                    reconciled = reconcile_receipt(receipt)
                except Exception as error:  # noqa: BLE001 - keep retryable state
                    receipt["error"] = str(error)
                    continue
                if not isinstance(reconciled, Mapping):
                    receipt["error"] = (
                        "The Drive upload is still being confirmed. "
                        "Retry unresolved receipts again."
                    )
                    continue
                drive_file = dict(reconciled)
                receipt["upload_uncertain"] = False
            else:
                try:
                    drive_file = dict(upload_receipt(receipt))
                except Exception as error:  # noqa: BLE001 - keep other receipts moving
                    if getattr(error, "retryable", False) and getattr(
                        error,
                        "upload_attempted",
                        True,
                    ) is not False:
                        receipt["upload_uncertain"] = True
                    receipt["error"] = str(error)
                    continue
            receipt["drive_file"] = drive_file
            receipt["content"] = b""
            try:
                reference = receipt_reference_from_drive_file(drive_file)
            except Exception as error:  # noqa: BLE001 - preserve Drive recovery pointer
                receipt["error"] = (
                    "The Drive file was uploaded, but its receipt metadata "
                    f"could not be read: {error}"
                )
                continue
            receipt["reference"] = reference
        receipt["content"] = b""
        try:
            link_receipt(reference)
        except Exception as error:  # noqa: BLE001 - retain uploaded file for retry
            receipt["error"] = str(error)
        else:
            receipt["linked"] = True
            receipt["error"] = ""


def receipt_creation_counts(workflow: Mapping[str, Any]) -> tuple[int, int]:
    """Return linked and unresolved receipt counts."""
    receipts = workflow.get("receipts", [])
    linked = sum(item.get("linked") is True for item in receipts)
    unresolved = len(receipts) - linked
    return linked, unresolved


def _receipt_folder(context: TransactionsContext) -> Mapping[str, object] | None:
    drive_settings = context.profile_secrets.get("google_drive")
    if not isinstance(drive_settings, Mapping):
        return None
    receipt_folder = drive_settings.get("receipt_folder")
    return receipt_folder if isinstance(receipt_folder, Mapping) else None


def _mark_workbook_data_changed(context: TransactionsContext) -> None:
    """Invalidate prepared exports after a confirmed receipt-reference write."""
    callback = getattr(context, "mark_workbook_data_changed", None)
    if callable(callback):
        callback()


def _process_context_receipts(
    context: TransactionsContext,
    workflow: MutableMapping[str, Any],
    receipt_folder: Mapping[str, object],
) -> None:
    linked_before, _unresolved_before = receipt_creation_counts(workflow)
    receipt_drive = context.get_drive_client(
        context.profile_key,
        context.configuration_revision,
    )
    transaction_id = str(workflow["transaction_id"])
    folder_id = str(receipt_folder["id"])
    process_receipt_recovery(
        workflow,
        upload_receipt=lambda receipt: receipt_drive.upload_receipt(
            profile_key=context.profile_key,
            transaction_id=transaction_id,
            folder_id=folder_id,
            original_name=str(receipt["original_name"]),
            content=bytes(receipt["content"]),
            mime_type=str(receipt["mime_type"]),
            receipt_id=str(receipt["receipt_id"]),
        ),
        reconcile_receipt=lambda receipt: receipt_drive.find_receipt_by_identity(
            profile_key=context.profile_key,
            transaction_id=transaction_id,
            folder_id=folder_id,
            receipt_id=str(receipt["receipt_id"]),
            content=bytes(receipt["content"]),
        ),
        link_receipt=lambda reference: context.storage.link_transaction_receipt(
            transaction_id,
            reference=reference,
        ),
    )
    linked_after, _unresolved_after = receipt_creation_counts(workflow)
    if linked_after > linked_before:
        _mark_workbook_data_changed(context)


def _editor_workflow(
    context: TransactionsContext,
    transaction_id: str,
) -> MutableMapping[str, Any] | None:
    workflow = st.session_state.get(
        receipt_editor_workflow_key(context.profile_key, transaction_id)
    )
    return workflow if isinstance(workflow, MutableMapping) else None


def _process_editor_receipts(
    context: TransactionsContext,
    workflow: MutableMapping[str, Any],
    receipt_folder: Mapping[str, object],
) -> None:
    """Process editor uploads through the same retry-safe receipt pipeline."""
    _process_context_receipts(context, workflow, receipt_folder)


def _start_editor_receipt_workflow(
    context: TransactionsContext,
    transaction_id: str,
    receipts: Sequence[Mapping[str, Any]],
    receipt_folder: Mapping[str, object],
) -> MutableMapping[str, Any]:
    workflow = new_receipt_creation_workflow(
        transaction_id,
        receipts,
        profile_key=context.profile_key,
        configuration_revision=context.configuration_revision,
        spreadsheet_id=str(context.profile_secrets.get("spreadsheet_id", "")),
        receipt_folder_id=str(receipt_folder.get("id", "")),
    )
    st.session_state[
        receipt_editor_workflow_key(context.profile_key, transaction_id)
    ] = workflow
    try:
        _process_editor_receipts(context, workflow, receipt_folder)
    except GoogleDriveError as error:
        workflow["configuration_error"] = str(error)
    return workflow


def _finish_editor_receipt_workflow(
    context: TransactionsContext,
    transaction_id: str,
    workflow: MutableMapping[str, Any],
) -> bool:
    if not _workflow_complete(workflow):
        return False
    linked, _unresolved = receipt_creation_counts(workflow)
    st.session_state.pop(
        receipt_editor_workflow_key(context.profile_key, transaction_id),
        None,
    )
    st.session_state[receipt_editor_notice_key(context.profile_key, transaction_id)] = (
        _new_editor_receipt_notice(
            context,
            f"{linked} receipt(s) uploaded and linked; 0 unresolved.",
        )
    )
    schedule_reset = getattr(context, "schedule_widget_reset", None)
    if callable(schedule_reset):
        schedule_reset(
            receipt_editor_upload_reset_key(
                context.profile_key,
                transaction_id,
            )
        )
    return True


def _new_editor_receipt_notice(
    context: TransactionsContext,
    message: str,
    receipt_folder: Mapping[str, object] | None = None,
    *,
    validated: bool = False,
) -> dict[str, str]:
    """Bind an editor notice to the profile storage it describes."""
    profile_secrets = getattr(context, "profile_secrets", {})
    if not isinstance(profile_secrets, Mapping):
        profile_secrets = {}
    selected_receipt_folder = receipt_folder
    if selected_receipt_folder is None:
        drive_settings = profile_secrets.get("google_drive")
        configured_folder = (
            drive_settings.get("receipt_folder")
            if isinstance(drive_settings, Mapping)
            else None
        )
        selected_receipt_folder = (
            configured_folder if isinstance(configured_folder, Mapping) else None
        )
    return {
        "message": message,
        "spreadsheet_id": str(profile_secrets.get("spreadsheet_id", "")),
        "receipt_folder_id": str(
            selected_receipt_folder.get("id", "")
            if selected_receipt_folder is not None
            else ""
        ),
        "validated_configuration": (
            _editor_receipt_configuration_key(context) if validated else ""
        ),
    }


def _editor_receipt_configuration_key(context: TransactionsContext) -> str:
    """Return the current profile storage identity used for notice validation."""
    profile_secrets = getattr(context, "profile_secrets", {})
    if not isinstance(profile_secrets, Mapping):
        profile_secrets = {}
    drive_settings = profile_secrets.get("google_drive")
    receipt_folder = (
        drive_settings.get("receipt_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    folder_id = (
        str(receipt_folder.get("id", ""))
        if isinstance(receipt_folder, Mapping)
        else ""
    )
    return f"{profile_secrets.get('spreadsheet_id', '')}\x00{folder_id}"


def _mark_editor_receipt_notice_validated(
    key: str,
    notice: object,
    configuration_key: str,
) -> None:
    """Bound a notice to the configuration under which it was checked."""
    if isinstance(notice, Mapping):
        updated_notice = dict(notice)
        updated_notice["validated_configuration"] = configuration_key
        st.session_state[key] = updated_notice


def _editor_receipt_notice_message(notice: object) -> str:
    """Read a current or legacy editor notice from session state."""
    if isinstance(notice, Mapping):
        return str(notice.get("message", "") or "")
    return str(notice or "")


def _editor_receipt_notice_requires_attention(message: str) -> bool:
    """Return whether a receipt notice represents an attention state."""
    return message in {
        EDITOR_RECEIPT_TRANSACTION_MISSING_NOTICE,
        EDITOR_RECEIPT_RECOVERY_CANCELED_NOTICE,
    }


def _editor_receipt_notice_matches_configuration(
    context: TransactionsContext,
    notice: object,
    receipt_folder: Mapping[str, object],
) -> bool:
    """Return whether an editor notice belongs to the active profile storage."""
    if not isinstance(notice, Mapping):
        return True
    expected_spreadsheet = str(notice.get("spreadsheet_id", ""))
    expected_folder = str(notice.get("receipt_folder_id", ""))
    profile_secrets = getattr(context, "profile_secrets", {})
    if not isinstance(profile_secrets, Mapping):
        profile_secrets = {}
    current_spreadsheet = str(profile_secrets.get("spreadsheet_id", ""))
    current_folder = str(receipt_folder.get("id", ""))
    return not (
        (expected_spreadsheet and expected_spreadsheet != current_spreadsheet)
        or (expected_folder and expected_folder != current_folder)
    )


def _cancel_editor_receipt_recovery(
    context: TransactionsContext,
    transaction_id: str,
) -> None:
    """Discard unresolved editor uploads without deleting Drive files."""
    st.session_state.pop(
        receipt_editor_workflow_key(context.profile_key, transaction_id),
        None,
    )
    schedule_reset = getattr(context, "schedule_widget_reset", None)
    if callable(schedule_reset):
        schedule_reset(
            receipt_editor_upload_reset_key(
                context.profile_key,
                transaction_id,
            )
        )
    st.session_state[receipt_editor_notice_key(context.profile_key, transaction_id)] = (
        _new_editor_receipt_notice(
            context,
            EDITOR_RECEIPT_RECOVERY_CANCELED_NOTICE,
        )
    )


def _receipt_recovery_file_id(receipt: Mapping[str, Any]) -> str:
    """Return a recovered receipt's known Drive ID, if one is available."""
    for key in ("reference", "drive_file"):
        value = receipt.get(key)
        if isinstance(value, Mapping):
            file_id = str(value.get("id") or "")
            if file_id:
                return file_id
    return ""


def _new_unresolved_receipt_count(
    unresolved_receipts: Sequence[Mapping[str, Any]],
    existing_receipt_ids: set[str],
) -> int:
    """Count unresolved receipts that would add a new transaction reference."""
    return sum(
        _receipt_recovery_file_id(receipt) not in existing_receipt_ids
        for receipt in unresolved_receipts
    )


def _reconcile_editor_workflow_references(
    workflow: MutableMapping[str, Any],
    fresh_receipt_references: Sequence[Mapping[str, Any]],
) -> None:
    """Drop linked workflow entries removed from the transaction in Sheets."""
    fresh_receipt_ids = {
        str(reference.get("id") or "")
        for reference in fresh_receipt_references
    }
    workflow["receipts"] = [
        receipt
        for receipt in workflow.get("receipts", [])
        if receipt.get("linked") is not True
        or _receipt_recovery_file_id(receipt) in fresh_receipt_ids
    ]


def _discard_editor_workflow_receipt(
    workflow: MutableMapping[str, Any],
    file_id: str,
) -> None:
    """Forget recovery for a receipt the user explicitly unlinked."""
    workflow["receipts"] = [
        receipt
        for receipt in workflow.get("receipts", [])
        if _receipt_recovery_file_id(receipt) != file_id
    ]


def _record_editor_receipt_linked(
    context: TransactionsContext,
    transaction_id: str,
    reference: Mapping[str, Any],
) -> bool:
    """Resolve matching editor recovery after an Unreferenced receipt link."""
    workflow = _editor_workflow(context, transaction_id)
    if workflow is None:
        return False
    file_id = str(reference.get("id", ""))
    if not file_id:
        return False
    matched = False
    for receipt in workflow.get("receipts", []):
        if not isinstance(receipt, MutableMapping) or receipt.get("linked") is True:
            continue
        saved_reference = receipt.get("reference")
        drive_file = receipt.get("drive_file")
        saved_file_id = (
            str(saved_reference.get("id", ""))
            if isinstance(saved_reference, Mapping)
            else str(drive_file.get("id", ""))
            if isinstance(drive_file, Mapping)
            else ""
        )
        if saved_file_id != file_id:
            continue
        receipt["reference"] = dict(reference)
        receipt["content"] = b""
        receipt["linked"] = True
        receipt["error"] = ""
        matched = True
    if not matched:
        return False
    try:
        fresh_receipt_references = _fresh_transaction_receipt_references(
            context,
            transaction_id,
        )
    except StorageError as error:
        workflow["configuration_error"] = (
            "The transaction could not be rechecked after linking the receipt. "
            f"Retry the remaining receipts again: {error}"
        )
        return False
    _reconcile_editor_workflow_references(
        workflow,
        fresh_receipt_references,
    )
    return _finish_editor_receipt_workflow(
        context,
        transaction_id,
        workflow,
    )


def _render_editor_receipt_recovery(
    context: TransactionsContext,
    transaction_id: str,
    receipt_folder: Mapping[str, object] | None,
    *,
    retry_available: bool = True,
    configuration_matches: bool = True,
) -> bool:
    """Render editor receipt recovery and return whether a workflow is active."""
    workflow = _editor_workflow(context, transaction_id)
    if workflow is None:
        return False
    linked, unresolved = receipt_creation_counts(workflow)
    unresolved_receipts = [
        receipt
        for receipt in workflow.get("receipts", [])
        if receipt.get("linked") is not True
    ]
    reference_only_retry = (
        unresolved == 1
        and isinstance(unresolved_receipts[0].get("reference"), Mapping)
    )
    retry_label = (
        "Retry linking uploaded receipt"
        if reference_only_retry
        else "Retry unresolved receipts"
    )
    if not unresolved and workflow.get("configuration_error"):
        retry_label = "Retry recovery check"
    if unresolved:
        st.warning(
            f"{linked} receipt(s) complete and {unresolved} receipt(s) "
            f"unresolved. Click {retry_label} to continue."
        )
        if reference_only_retry:
            st.caption(
                "The unresolved receipt is already uploaded to Google Drive; "
                "retry links the existing file before another upload."
            )
        for receipt in workflow.get("receipts", []):
            if receipt.get("linked") is not True and receipt.get("error"):
                st.caption(
                    f"{receipt.get('original_name', 'Receipt')}: "
                    f"{receipt['error']}"
                )
        st.caption(
            "Canceling discards unresolved local files. Files already uploaded "
            "remain in Google Drive and can be linked from the Unreferenced "
            "receipt workflow."
        )
    if workflow.get("configuration_error"):
        st.error(str(workflow["configuration_error"]))
    retry_requested = False
    confirmation_only_retry = not unresolved and bool(
        workflow.get("configuration_error")
    )
    if (unresolved or workflow.get("configuration_error")) and configuration_matches and (
        retry_available or confirmation_only_retry
    ):
        retry_requested = st.button(
            retry_label,
            type="primary",
            key=f"retry-editor-receipts-{context.profile_key}-{transaction_id}",
        )
    elif configuration_matches and (unresolved or workflow.get("configuration_error")):
        st.info(
            "Connect Google Drive and select a receipt folder before retrying "
            "receipt recovery."
        )
    cancel_requested = unresolved and st.button(
        "Cancel recovery",
        key=f"cancel-editor-receipts-{context.profile_key}-{transaction_id}",
    )
    if cancel_requested:
        _cancel_editor_receipt_recovery(context, transaction_id)
        st.rerun()
    if retry_requested:
        workflow.pop("configuration_error", None)
        if unresolved and (
            receipt_folder is None
            or not _workflow_configuration_matches(
                context,
                workflow,
                receipt_folder,
            )
        ):
            st.rerun()
        try:
            fresh_receipt_references = _fresh_transaction_receipt_references(
                context,
                transaction_id,
            )
            fresh_receipt_ids = {
                str(reference["id"])
                for reference in fresh_receipt_references
            }
            _reconcile_editor_workflow_references(
                workflow,
                fresh_receipt_references,
            )
            unresolved_receipts = [
                receipt
                for receipt in workflow.get("receipts", [])
                if receipt.get("linked") is not True
            ]
            unresolved = len(unresolved_receipts)
            new_unresolved_count = _new_unresolved_receipt_count(
                unresolved_receipts,
                fresh_receipt_ids,
            )
            if len(fresh_receipt_references) + new_unresolved_count > MAX_RECEIPT_REFERENCES:
                raise GoogleDriveAccessError(
                    "A transaction can reference no more than 100 receipts. "
                    "Remove an existing receipt reference or retry with fewer "
                    "unresolved receipts."
                )
            if any(
                receipt.get("linked") is not True
                for receipt in workflow.get("receipts", [])
            ):
                _process_editor_receipts(context, workflow, receipt_folder)
            _finish_editor_receipt_workflow(context, transaction_id, workflow)
        except GoogleDriveError as error:
            workflow["configuration_error"] = str(error)
        except StorageError as error:
            if "no longer exists" in str(error).casefold():
                st.session_state.pop(
                    receipt_editor_workflow_key(context.profile_key, transaction_id),
                    None,
                )
                st.session_state[
                    receipt_editor_notice_key(
                        context.profile_key,
                        transaction_id,
                    )
                ] = _new_editor_receipt_notice(
                    context,
                    EDITOR_RECEIPT_TRANSACTION_MISSING_NOTICE,
                    receipt_folder,
                    validated=True,
                )
            else:
                workflow["configuration_error"] = (
                    "The transaction could not be rechecked or linked. "
                    f"Retry unresolved receipts again: {error}"
                )
        st.rerun()
    return True


def _workflow_complete(workflow: Mapping[str, Any]) -> bool:
    return receipt_creation_counts(workflow)[1] == 0


def _workflow_has_uploaded_receipt(workflow: Mapping[str, Any]) -> bool:
    """Return whether recovery retains a Drive file for any receipt."""
    return any(
        isinstance(receipt, Mapping)
        and (
            isinstance(receipt.get("reference"), Mapping)
            or isinstance(receipt.get("drive_file"), Mapping)
            or receipt.get("upload_uncertain") is True
        )
        for receipt in workflow.get("receipts", [])
    )


def _transaction_still_exists(
    context: TransactionsContext,
    transaction_id: str,
) -> bool:
    """Confirm the recovery target still exists in fresh Sheets data."""
    return any(
        str(transaction.get("id", "")) == transaction_id
        for transaction in context.storage.list_transactions(_force_refresh=True)
    )


def _fresh_transaction_receipt_count(
    context: TransactionsContext,
    transaction_id: str,
) -> int:
    """Return the selected transaction's receipt count from fresh Sheets data."""
    return len(_fresh_transaction_receipt_references(context, transaction_id))


def _fresh_transaction_receipt_references(
    context: TransactionsContext,
    transaction_id: str,
) -> list[dict[str, Any]]:
    """Return the selected transaction's references from fresh Sheets data."""
    for transaction in context.storage.list_transactions(_force_refresh=True):
        if str(transaction.get("id", "")) == transaction_id:
            return decode_receipt_references(
                transaction.get("receipt_references", "")
            )
    raise StorageError(
        "The selected transaction no longer exists. Refresh the ledger before "
        "uploading receipts."
    )


def clear_missing_editor_receipt_recoveries(
    context: TransactionsContext,
    transactions: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Discard editor recovery whose transaction disappeared from fresh Sheets data."""
    notices: list[str] = []
    existing_transaction_ids = {
        str(transaction.get("id", ""))
        for transaction in transactions
        if str(transaction.get("id", ""))
    }
    processed_transaction_ids: set[str] = set()
    profile_secrets = getattr(context, "profile_secrets", {})
    if not isinstance(profile_secrets, Mapping):
        profile_secrets = {}
    current_spreadsheet = str(profile_secrets.get("spreadsheet_id", ""))
    key_prefix = receipt_editor_workflow_key_prefix(context.profile_key)
    current_receipt_folder = _receipt_folder(context)
    current_folder_id = str(
        current_receipt_folder.get("id", "")
        if current_receipt_folder is not None
        else ""
    )
    current_configuration_key = _editor_receipt_configuration_key(context)
    for key in list(st.session_state):
        if not isinstance(key, str) or not key.startswith(key_prefix):
            continue
        workflow = st.session_state.get(key)
        if not isinstance(workflow, Mapping):
            continue
        workflow_spreadsheet = str(workflow.get("spreadsheet_id", ""))
        workflow_folder = str(workflow.get("receipt_folder_id", ""))
        if (
            workflow_spreadsheet
            and workflow_spreadsheet != current_spreadsheet
        ) or (workflow_folder and workflow_folder != current_folder_id):
            continue
        transaction_id = str(workflow.get("transaction_id", ""))
        if not transaction_id or transaction_id in existing_transaction_ids:
            continue
        st.session_state.pop(key, None)
        notice = EDITOR_RECEIPT_TRANSACTION_MISSING_NOTICE
        st.session_state[
            receipt_editor_notice_key(
                context.profile_key,
                transaction_id,
            )
        ] = _new_editor_receipt_notice(context, notice, validated=True)
        notices.append(notice)
        processed_transaction_ids.add(transaction_id)

    notice_prefix = receipt_editor_notice_key_prefix(context.profile_key)
    for key in list(st.session_state):
        if not isinstance(key, str) or not key.startswith(notice_prefix):
            continue
        transaction_id = key[len(notice_prefix) :]
        if not transaction_id or transaction_id in processed_transaction_ids:
            continue
        notice = st.session_state.get(key)
        if isinstance(notice, Mapping):
            notice_spreadsheet = str(notice.get("spreadsheet_id", ""))
            notice_folder = str(notice.get("receipt_folder_id", ""))
            if (
                notice_spreadsheet
                and notice_spreadsheet != current_spreadsheet
            ) or (notice_folder and notice_folder != current_folder_id):
                _mark_editor_receipt_notice_validated(
                    key,
                    notice,
                    current_configuration_key,
                )
                continue
        if transaction_id in existing_transaction_ids:
            if isinstance(notice, Mapping):
                _mark_editor_receipt_notice_validated(
                    key,
                    notice,
                    current_configuration_key,
                )
            elif _editor_receipt_notice_message(notice):
                st.session_state[key] = _new_editor_receipt_notice(
                    context,
                    _editor_receipt_notice_message(notice),
                    validated=True,
                )
            else:
                st.session_state.pop(key, None)
            continue
        notice = st.session_state.pop(key, None)
        if _editor_receipt_notice_message(notice):
            notices.append(EDITOR_RECEIPT_TRANSACTION_MISSING_NOTICE)
    return notices


def editor_receipt_recovery_active(context: TransactionsContext) -> bool:
    """Return whether this profile has editor recovery state to reconcile."""
    workflow_key_prefix = receipt_editor_workflow_key_prefix(context.profile_key)
    notice_key_prefix = receipt_editor_notice_key_prefix(context.profile_key)
    current_configuration_key = _editor_receipt_configuration_key(context)
    for key in st.session_state:
        if not isinstance(key, str):
            continue
        if key.startswith(workflow_key_prefix):
            workflow = st.session_state.get(key)
            if not isinstance(workflow, Mapping):
                return True
            workflow_spreadsheet = str(workflow.get("spreadsheet_id", ""))
            workflow_folder = str(workflow.get("receipt_folder_id", ""))
            if not any((workflow_spreadsheet, workflow_folder)):
                return True
            if (
                f"{workflow_spreadsheet}\x00{workflow_folder}"
                == current_configuration_key
            ):
                return True
            continue
        if key.startswith(notice_key_prefix):
            notice = st.session_state.get(key)
            if not isinstance(notice, Mapping):
                return True
            if (
                str(notice.get("validated_configuration", ""))
                != current_configuration_key
            ):
                return True
    return False


def editor_receipt_recovery_transaction_ids(
    context: TransactionsContext,
) -> list[str]:
    """Return this profile's editor recovery targets for independent rendering."""
    workflow_key_prefix = receipt_editor_workflow_key_prefix(context.profile_key)
    transaction_ids: set[str] = set()
    for key in list(st.session_state):
        if not isinstance(key, str) or not key.startswith(workflow_key_prefix):
            continue
        workflow = st.session_state.get(key)
        if not isinstance(workflow, Mapping):
            continue
        transaction_id = str(workflow.get("transaction_id", ""))
        if transaction_id:
            transaction_ids.add(transaction_id)
    return sorted(transaction_ids)


def editor_receipt_notice_transaction_ids(
    context: TransactionsContext,
) -> list[str]:
    """Return this profile's editor notice targets for independent rendering."""
    notice_key_prefix = receipt_editor_notice_key_prefix(context.profile_key)
    transaction_ids: set[str] = set()
    for key in list(st.session_state):
        if isinstance(key, str) and key.startswith(notice_key_prefix):
            transaction_id = key[len(notice_key_prefix) :]
            if transaction_id:
                transaction_ids.add(transaction_id)
    return sorted(transaction_ids)


def render_editor_receipt_notice(
    context: TransactionsContext,
    transaction_id: str,
) -> bool:
    """Render and consume a matching editor notice outside a transaction row."""
    key = receipt_editor_notice_key(context.profile_key, transaction_id)
    notice = st.session_state.get(key)
    receipt_folder = _receipt_folder(context)
    if isinstance(notice, Mapping):
        profile_secrets = getattr(context, "profile_secrets", {})
        if not isinstance(profile_secrets, Mapping):
            profile_secrets = {}
        expected_spreadsheet = str(notice.get("spreadsheet_id", ""))
        expected_folder = str(notice.get("receipt_folder_id", ""))
        current_spreadsheet = str(profile_secrets.get("spreadsheet_id", ""))
        current_folder = str(
            receipt_folder.get("id", "") if receipt_folder is not None else ""
        )
        if (
            expected_spreadsheet
            and expected_spreadsheet != current_spreadsheet
        ) or (expected_folder and expected_folder != current_folder):
            return False
    message = _editor_receipt_notice_message(st.session_state.pop(key, None))
    if not message:
        return False
    if _editor_receipt_notice_requires_attention(message):
        st.warning(message)
    else:
        st.success(message)
    return True


def render_filtered_editor_receipt_recovery(
    context: TransactionsContext,
    transaction_id: str,
) -> bool:
    """Render recovery for a transaction hidden by the active ledger filters."""
    receipt_folder = _receipt_folder(context)
    workflow = _editor_workflow(context, transaction_id)
    configuration_matches = True
    if workflow is not None:
        expected_spreadsheet = str(workflow.get("spreadsheet_id", ""))
        expected_folder = str(workflow.get("receipt_folder_id", ""))
        if expected_spreadsheet or expected_folder:
            if receipt_folder is None:
                workflow["configuration_error"] = (
                    "The profile's Google Sheets or Drive receipt configuration "
                    "changed while this receipt was waiting for recovery. Restore "
                    "the previous profile configuration before retrying."
                )
                configuration_matches = False
            else:
                configuration_matches = _workflow_configuration_matches(
                    context,
                    workflow,
                    receipt_folder,
                )
    retry_available = False
    if receipt_folder is not None and configuration_matches:
        try:
            context.get_drive_client(
                context.profile_key,
                context.configuration_revision,
            )
        except GoogleDriveError as error:
            st.error(str(error))
        else:
            retry_available = True
    return _render_editor_receipt_recovery(
        context,
        transaction_id,
        receipt_folder,
        retry_available=retry_available,
        configuration_matches=configuration_matches,
    )


def finish_receipt_creation_if_complete(
    context: TransactionsContext,
    workflow: MutableMapping[str, Any],
) -> bool:
    """Clear successful recovery state and schedule the form reset."""
    if not _workflow_complete(workflow):
        return False
    linked, _unresolved = receipt_creation_counts(workflow)
    st.session_state.pop(
        receipt_creation_workflow_key(context.profile_key),
        None,
    )
    context.schedule_widget_reset("reset_add_transaction_form")
    notice = (
        f"Transaction saved and {linked} receipt(s) linked."
    )
    st.session_state["write_success_notice"] = notice
    return True


def clear_receipt_creation_recovery(
    context: TransactionsContext,
    transaction_id: str,
) -> None:
    """Discard recovery for a transaction that was deliberately deleted."""
    workflow = st.session_state.get(
        receipt_creation_workflow_key(context.profile_key)
    )
    if (
        isinstance(workflow, Mapping)
        and str(workflow.get("transaction_id", "")) == str(transaction_id)
    ):
        st.session_state.pop(
            receipt_creation_workflow_key(context.profile_key),
            None,
        )
    st.session_state.pop(
        receipt_editor_workflow_key(context.profile_key, transaction_id),
        None,
    )
    st.session_state.pop(
        receipt_editor_notice_key(context.profile_key, transaction_id),
        None,
    )


def _workflow_configuration_matches(
    context: TransactionsContext,
    workflow: MutableMapping[str, Any],
    receipt_folder: Mapping[str, object],
) -> bool:
    expected_revision = str(workflow.get("configuration_revision", ""))
    expected_spreadsheet = str(workflow.get("spreadsheet_id", ""))
    expected_folder = str(workflow.get("receipt_folder_id", ""))
    profile_secrets = getattr(context, "profile_secrets", {})
    if not isinstance(profile_secrets, Mapping):
        profile_secrets = {}
    current_spreadsheet = str(profile_secrets.get("spreadsheet_id", ""))
    current_folder = str(receipt_folder.get("id", ""))
    if not any((expected_spreadsheet, expected_folder)):
        return (
            not expected_revision
            or expected_revision == str(context.configuration_revision)
        )
    if (
        expected_spreadsheet != current_spreadsheet
        or expected_folder != current_folder
    ):
        workflow["configuration_error"] = (
            "The profile's Google Sheets or Drive receipt configuration "
            "changed while this receipt was waiting for recovery. Restore "
            "the previous profile configuration before retrying."
        )
        return False
    return True


def _link_recovery_configuration_matches(
    context: TransactionsContext,
    recovery: Mapping[str, Any],
    receipt_folder: Mapping[str, object],
) -> bool:
    """Keep post-create link recovery bound to its selected profile storage."""
    expected_spreadsheet = str(recovery.get("spreadsheet_id", ""))
    expected_folder = str(recovery.get("receipt_folder_id", ""))
    if not any((expected_spreadsheet, expected_folder)):
        return True
    return (
        expected_spreadsheet
        == str(context.profile_secrets.get("spreadsheet_id", ""))
        and expected_folder == str(receipt_folder.get("id", ""))
    )


def handle_confirmed_transaction_receipts(
    context: TransactionsContext,
    transaction: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
) -> None:
    """Upload/link selected receipts after the Sheets write is confirmed."""
    workflow = new_receipt_creation_workflow(
        str(transaction["id"]),
        receipts,
        profile_key=context.profile_key,
        configuration_revision=context.configuration_revision,
        spreadsheet_id=str(context.profile_secrets.get("spreadsheet_id", "")),
        receipt_folder_id=str(
            (_receipt_folder(context) or {}).get("id", "")
        ),
    )
    st.session_state[receipt_creation_workflow_key(context.profile_key)] = workflow
    receipt_folder = _receipt_folder(context)
    if receipt_folder is None:
        workflow["configuration_error"] = (
            "Google Drive receipt storage is not configured for this profile."
        )
        return
    try:
        _process_context_receipts(context, workflow, receipt_folder)
    except GoogleDriveError as error:
        workflow["configuration_error"] = str(error)
    finish_receipt_creation_if_complete(context, workflow)


def _render_receipt_workflow_status(workflow: Mapping[str, Any]) -> None:
    linked, unresolved = receipt_creation_counts(workflow)
    if unresolved:
        st.warning(
            f"The transaction is saved: {linked} receipt(s) complete and "
            f"{unresolved} receipt(s) unresolved. Click Retry unresolved "
            "receipts to continue."
        )
        for receipt in workflow.get("receipts", []):
            if receipt.get("linked") is not True and receipt.get("error"):
                st.caption(
                    f"{receipt.get('original_name', 'Receipt')}: "
                    f"{receipt['error']}"
                )


def render_receipt_creation_recovery(context: TransactionsContext) -> bool:
    """Render and optionally resume the current session's receipt recovery."""
    workflow = st.session_state.get(
        receipt_creation_workflow_key(context.profile_key)
    )
    if not isinstance(workflow, MutableMapping):
        return False
    transaction_id = str(workflow.get("transaction_id", ""))
    if not transaction_id:
        st.session_state.pop(
            receipt_creation_workflow_key(context.profile_key),
            None,
        )
        return False
    st.info(
        f"Transaction {transaction_id} is saved in Google Sheets. "
        "Receipt processing can be resumed independently."
    )
    if workflow.get("configuration_error"):
        st.error(str(workflow["configuration_error"]))
    _render_receipt_workflow_status(workflow)
    retry_error = st.empty()
    if not _workflow_complete(workflow) and st.button(
        "Retry unresolved receipts",
        type="primary",
        key=f"retry-receipts-{transaction_id}",
    ):
        receipt_folder = _receipt_folder(context)
        if receipt_folder is None:
            retry_error.error(
                "Connect Google Drive and configure the profile's receipt "
                "folder before retrying."
            )
        else:
            workflow.pop("configuration_error", None)
            if _workflow_configuration_matches(context, workflow, receipt_folder):
                try:
                    if not _transaction_still_exists(context, transaction_id):
                        st.session_state.pop(
                            receipt_creation_workflow_key(context.profile_key),
                            None,
                        )
                        if _workflow_has_uploaded_receipt(workflow):
                            st.session_state["write_success_notice"] = (
                                "The saved transaction no longer exists. "
                                "Create the replacement transaction without "
                                "re-uploading these files, then link the "
                                "existing files from the Unreferenced receipt "
                                "workflow."
                            )
                        else:
                            st.session_state["write_success_notice"] = (
                                "The saved transaction no longer exists. "
                                "Start a new transaction and select its receipts again."
                            )
                    else:
                        _process_context_receipts(
                            context,
                            workflow,
                            receipt_folder,
                        )
                except GoogleDriveError as error:
                    workflow["configuration_error"] = str(error)
                except StorageError as error:
                    workflow["configuration_error"] = (
                        "The saved transaction could not be rechecked. "
                        f"Retry unresolved receipts again: {error}"
                    )
                finish_receipt_creation_if_complete(context, workflow)
            st.rerun()
    return True


def render_receipts(
    context: TransactionsContext,
    *,
    selected: Mapping[str, object],
    all_transactions: Sequence[Mapping[str, object]],
    edit_id: str,
) -> None:
    """Render receipt links, unlinking, relinking, and upload for one row."""
    st.divider()
    st.subheader("Receipt")
    selected_profile = context.profile_secrets
    drive_settings = selected_profile.get("google_drive")
    receipt_folder = (
        drive_settings.get("receipt_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    if not isinstance(receipt_folder, Mapping):
        _render_editor_receipt_recovery(
            context,
            edit_id,
            None,
            retry_available=False,
        )
        st.info(
            "Connect Google Drive and select a receipt folder from "
            "the local Account settings page. Until then, store the "
            f"receipt manually as `{edit_id}-original-file-name`."
        )
    else:
        try:
            receipt_drive = context.get_drive_client(
                context.profile_key,
                context.configuration_revision,
            )
        except GoogleDriveError as error:
            _render_editor_receipt_recovery(
                context,
                edit_id,
                receipt_folder,
                retry_available=False,
            )
            st.error(str(error))
        else:
            receipt_action_scope = (
                f"{context.profile_key}-{edit_id}"
            )
            receipt_candidate_key = (
                f"receipt-unlink-candidate-{receipt_action_scope}"
            )
            receipt_notice_key = (
                f"receipt-unlink-notice-{receipt_action_scope}"
            )
            receipt_link_recovery_key = (
                f"receipt-link-recovery-{receipt_action_scope}"
            )
            editor_receipt_notice_key = receipt_editor_notice_key(
                context.profile_key,
                edit_id,
            )
            reset_editor_upload = getattr(
                context,
                "reset_widget_state_if_requested",
                None,
            )
            if callable(reset_editor_upload):
                reset_editor_upload(
                    receipt_editor_upload_reset_key(
                        context.profile_key,
                        edit_id,
                    ),
                    keys=(f"receipt-upload-{edit_id}",),
                )
            editor_receipt_workflow_active = _render_editor_receipt_recovery(
                context,
                edit_id,
                receipt_folder,
                retry_available=True,
            )
            editor_receipt_notice = st.session_state.get(
                editor_receipt_notice_key
            )
            if _editor_receipt_notice_matches_configuration(
                context,
                editor_receipt_notice,
                receipt_folder,
            ):
                editor_receipt_notice = st.session_state.pop(
                    editor_receipt_notice_key,
                    None,
                )
            else:
                editor_receipt_notice = None
            editor_receipt_notice_message = _editor_receipt_notice_message(
                editor_receipt_notice
            )
            if editor_receipt_notice_message:
                if _editor_receipt_notice_requires_attention(
                    editor_receipt_notice_message
                ):
                    st.warning(editor_receipt_notice_message)
                else:
                    st.success(editor_receipt_notice_message)
            receipt_notice = st.session_state.pop(
                receipt_notice_key,
                None,
            )
            if receipt_notice:
                st.success(str(receipt_notice))
            link_recovery = st.session_state.get(receipt_link_recovery_key)
            recovery_reference: Mapping[str, object] | None = None
            recovery_configuration_matches = True
            if isinstance(link_recovery, Mapping):
                recovery_configuration_matches = (
                    _link_recovery_configuration_matches(
                        context,
                        link_recovery,
                        receipt_folder,
                    )
                )
                candidate_reference = link_recovery.get("reference")
                if isinstance(candidate_reference, Mapping):
                    recovery_reference = candidate_reference
                if isinstance(recovery_reference, Mapping):
                    if not recovery_configuration_matches:
                        st.error(
                            "The receipt's Google Sheets or Drive folder "
                            "configuration changed while it was waiting for "
                            "link recovery. Restore the previous selected "
                            "profile configuration before retrying."
                        )
                    else:
                        st.warning(
                            "This receipt is already uploaded to Google Drive. "
                            "Retry linking the existing file before uploading another copy. "
                            f"{link_recovery.get('error', '')}"
                        )
                    link_retry_error = st.empty()
                    if recovery_configuration_matches and st.button(
                        "Retry linking uploaded receipt",
                        type="primary",
                        key=(
                            "receipt-link-retry-"
                            f"{receipt_action_scope}"
                        ),
                    ):
                        try:
                            context.storage.link_transaction_receipt(
                                edit_id,
                                reference=recovery_reference,
                            )
                        except StorageError as error:
                            link_retry_error.error(
                                "The existing receipt could not be linked. "
                                f"{error}"
                            )
                        else:
                            _mark_workbook_data_changed(context)
                            st.session_state.pop(
                                receipt_link_recovery_key,
                                None,
                            )
                            st.session_state[receipt_notice_key] = (
                                "Receipt linked: "
                                f"{recovery_reference['name']}"
                            )
                            st.rerun()

            raw_receipt_references = selected.get(
                "receipt_references",
                "",
            )
            references_ready = True
            try:
                receipt_references = decode_receipt_references(
                    raw_receipt_references
                )
            except StorageError as error:
                references_ready = False
                receipt_references = []
                st.error(str(error))
            if references_ready and raw_receipt_references == "":
                try:
                    legacy_receipts = receipt_drive.list_receipts(
                        profile_key=context.profile_key,
                        transaction_id=edit_id,
                        folder_id=str(receipt_folder["id"]),
                    )
                    receipt_references = [
                        receipt_reference_from_drive_file(receipt)
                        for receipt in legacy_receipts
                        if receipt.get("id")
                    ]
                    context.storage.set_transaction_receipt_references(
                        edit_id,
                        receipt_references,
                    )
                    _mark_workbook_data_changed(context)
                except (
                    GoogleDriveError,
                    ReceiptManifestError,
                    StorageError,
                ) as error:
                    references_ready = False
                    st.error(
                        "Existing receipt references could not be "
                        f"initialized. {error}"
                    )

            receipt_ids = {
                reference["id"]
                for reference in receipt_references
            }
            if (
                st.session_state.get(receipt_candidate_key)
                not in receipt_ids
            ):
                st.session_state.pop(receipt_candidate_key, None)
            if references_ready and receipt_references:
                for reference in receipt_references:
                    receipt_id = reference["id"]
                    name = reference["name"]
                    link = (
                        "https://drive.google.com/open?id="
                        f"{receipt_id}"
                    )
                    receipt_column, delete_column = st.columns(
                        [4, 1]
                    )
                    with receipt_column:
                        if link:
                            st.link_button(name, link)
                        else:
                            st.caption(name)
                    with delete_column:
                        if receipt_id and st.button(
                            "Remove receipt",
                            key=(
                                "receipt-unlink-request-"
                                f"{receipt_action_scope}-{receipt_id}"
                            ),
                            width="stretch",
                        ):
                            st.session_state[
                                receipt_candidate_key
                            ] = receipt_id
                            st.rerun()
                    if (
                        receipt_id
                        and st.session_state.get(
                            receipt_candidate_key
                        )
                        == receipt_id
                    ):
                        st.warning(
                            f"Remove `{name}` from this transaction? "
                            "The file will remain in Google Drive."
                        )
                        unlink_error = st.empty()
                        cancel_column, confirm_column = st.columns(2)
                        if cancel_column.button(
                            "Cancel",
                            key=(
                                "receipt-unlink-cancel-"
                                f"{receipt_action_scope}-{receipt_id}"
                            ),
                            width="stretch",
                        ):
                            st.session_state.pop(
                                receipt_candidate_key,
                                None,
                            )
                            st.rerun()
                        if confirm_column.button(
                            "Remove reference",
                            type="primary",
                            key=(
                                "receipt-unlink-confirm-"
                                f"{receipt_action_scope}-{receipt_id}"
                            ),
                            width="stretch",
                        ):
                            try:
                                context.storage.unlink_transaction_receipt(
                                    edit_id,
                                    file_id=receipt_id,
                                )
                            except StorageError as error:
                                unlink_error.error(
                                    "Receipt reference was not "
                                    "removed. "
                                    f"{error}"
                                )
                            else:
                                _mark_workbook_data_changed(context)
                                workflow = _editor_workflow(context, edit_id)
                                if workflow is not None:
                                    _discard_editor_workflow_receipt(
                                        workflow,
                                        receipt_id,
                                    )
                                    _finish_editor_receipt_workflow(
                                        context,
                                        edit_id,
                                        workflow,
                                    )
                                st.session_state.pop(
                                    receipt_candidate_key,
                                    None,
                                )
                                st.session_state[
                                    receipt_notice_key
                                ] = (
                                    f"Receipt removed: {name}. "
                                    "The file remains in Google "
                                    "Drive."
                                )
                                st.rerun()
            if references_ready:
                referenced_receipt_ids: set[str] = set()
                uninitialized_transaction_ids: set[str] = set()
                for transaction in all_transactions:
                    if transaction["id"] == edit_id:
                        referenced_receipt_ids.update(
                            receipt_ids
                        )
                        continue
                    raw_references = transaction.get(
                        "receipt_references",
                        "",
                    )
                    if raw_references == "":
                        uninitialized_transaction_ids.add(
                            transaction["id"]
                        )
                        continue
                    if raw_references == "[]":
                        continue
                    try:
                        referenced_receipt_ids.update(
                            reference["id"]
                            for reference in (
                                decode_receipt_references(
                                    raw_references
                                )
                            )
                        )
                    except StorageError:
                        uninitialized_transaction_ids.add(
                            transaction["id"]
                        )
                try:
                    profile_receipts = (
                        receipt_drive.list_profile_receipts(
                            profile_key=context.profile_key,
                            folder_id=str(receipt_folder["id"]),
                        )
                    )
                except GoogleDriveError as error:
                    st.error(
                        "Unreferenced Google Drive receipts could "
                        f"not be listed. {error}"
                    )
                else:
                    unreferenced_receipts = []
                    receipts_needing_backfill = 0
                    for receipt in profile_receipts:
                        receipt_id = str(
                            receipt.get("id", "")
                        )
                        properties = receipt.get(
                            "appProperties"
                        )
                        legacy_transaction_id = (
                            str(
                                properties.get(
                                    "tabulaRasaTransaction",
                                    "",
                                )
                            )
                            if isinstance(properties, Mapping)
                            else ""
                        )
                        if (
                            receipt_id
                            and receipt_id
                            not in referenced_receipt_ids
                            and legacy_transaction_id
                            not in (
                                uninitialized_transaction_ids
                            )
                        ):
                            try:
                                unreferenced_receipts.append(
                                    receipt_reference_from_drive_file(
                                        receipt
                                    )
                                )
                            except ReceiptManifestError:
                                receipts_needing_backfill += 1
                    if receipts_needing_backfill:
                        st.warning(
                            f"{receipts_needing_backfill} receipt(s) "
                            "need integrity metadata before they can be linked."
                        )
                    if unreferenced_receipts:
                        unreferenced_by_id = {
                            receipt["id"]: receipt
                            for receipt in unreferenced_receipts
                        }
                        existing_receipt_id = st.selectbox(
                            "Unreferenced receipt",
                            list(unreferenced_by_id),
                            format_func=lambda file_id: (
                                unreferenced_by_id[file_id][
                                    "name"
                                ]
                            ),
                            key=(
                                "receipt-existing-select-"
                                f"{receipt_action_scope}"
                            ),
                            help=(
                                "App-managed files in this "
                                "profile's receipt folder that are "
                                "not linked to another transaction."
                            ),
                        )
                        link_error = st.empty()
                        if st.button(
                            "Link selected receipt",
                            key=(
                                "receipt-existing-link-"
                                f"{receipt_action_scope}"
                            ),
                        ):
                            existing_receipt = (
                                unreferenced_by_id[
                                    existing_receipt_id
                                ]
                            )
                            try:
                                context.storage.link_transaction_receipt(
                                    edit_id,
                                    reference=existing_receipt,
                                )
                            except StorageError as error:
                                link_error.error(
                                    "The receipt could not be "
                                    f"linked. {error}"
                                )
                            else:
                                _mark_workbook_data_changed(context)
                                editor_workflow_finished = (
                                    _record_editor_receipt_linked(
                                        context,
                                        edit_id,
                                        existing_receipt,
                                    )
                                )
                                if isinstance(recovery_reference, Mapping):
                                    st.session_state.pop(
                                        receipt_link_recovery_key,
                                        None,
                                    )
                                if not editor_workflow_finished:
                                    st.session_state[
                                        receipt_notice_key
                                    ] = (
                                        "Receipt linked: "
                                        f"{existing_receipt['name']}"
                                    )
                                st.rerun()
                    else:
                        st.caption(
                            "No unreferenced receipts are "
                            "available in Google Drive."
                        )
                receipt_uploads = None
                if (
                    not isinstance(recovery_reference, Mapping)
                    and not editor_receipt_workflow_active
                ):
                    receipt_uploads = st.file_uploader(
                        "Upload receipt",
                        type=RECEIPT_UPLOAD_TYPES,
                        accept_multiple_files=True,
                        key=f"receipt-upload-{edit_id}",
                        help=(
                            "Select one or more PDF, PNG, JPG, JPEG, WEBP, "
                            "or HEIC files. Each file must be non-empty and "
                            "no larger than 20 MB; the selected batch must "
                            "not exceed 200 MB total."
                        ),
                    )
                if receipt_uploads:
                    st.caption(
                        "Original filenames are kept safely. If a name already "
                        "exists, a numeric suffix will be added. All selected "
                        "files are validated before any upload begins."
                    )
                    upload_error = st.empty()
                    if st.button(
                        "Upload receipt to Google Drive",
                        type="primary",
                        key=f"receipt-upload-button-{edit_id}",
                    ):
                        try:
                            prepared_receipts = prepare_receipt_uploads(
                                receipt_uploads,
                            )
                        except (ValueError, GoogleDriveAccessError) as error:
                            upload_error.error(f"Receipt validation failed: {error}")
                        else:
                            try:
                                final_receipt_count = _fresh_transaction_receipt_count(
                                    context,
                                    edit_id,
                                )
                                if (
                                    final_receipt_count + len(prepared_receipts)
                                    > MAX_RECEIPT_REFERENCES
                                ):
                                    raise GoogleDriveAccessError(
                                        "A transaction can reference no more than "
                                        "100 receipts. Remove an existing receipt "
                                        "reference or select fewer files."
                                    )
                                workflow = _start_editor_receipt_workflow(
                                    context,
                                    edit_id,
                                    prepared_receipts,
                                    receipt_folder,
                                )
                            except (StorageError, GoogleDriveAccessError) as error:
                                upload_error.error(
                                    "The selected transaction could not be "
                                    f"rechecked before upload. {error}"
                                )
                            else:
                                if workflow is not None:
                                    _finish_editor_receipt_workflow(
                                        context,
                                        edit_id,
                                        workflow,
                                    )
                                    st.rerun()
