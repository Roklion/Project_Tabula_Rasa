from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import secrets
from typing import Any

from tabula_rasa.document_names import safe_receipt_filename as safe_receipt_filename

from tabula_rasa.application.documents import (
    DocumentValidationError,
    validate_receipt_upload as validate_document_upload,
)

from tabula_rasa.receipt_manifest import (
    DRIVE_ID_PATTERN as RECEIPT_DRIVE_ID_PATTERN,
    RECEIPT_ID_PATTERN,
    SHA256_PATTERN,
    ReceiptManifestError,
    receipt_reference_from_drive_file,
    validate_receipt_filename,
)

from .client import _escape_query_value
from .errors import (
    DRIVE_API_ROOT, MAX_RECEIPT_BYTES,
    GoogleDriveAccessError, GoogleDriveConflictError,
    GoogleDriveError, _json_response,
)
from .oauth import _clean_text

def validate_receipt_upload(
    original_name: str,
    content: bytes,
) -> None:
    """Validate the shared receipt upload contract before any write."""
    try:
        validate_document_upload(original_name, content)
    except DocumentValidationError as error:
        raise GoogleDriveAccessError(str(error)) from error


def suffixed_receipt_filename(filename: str, occurrence: int) -> str:
    """Add a numeric duplicate suffix before a filename extension."""
    if occurrence <= 1:
        return filename
    dot_index = filename.rfind(".")
    if dot_index > 0:
        stem = filename[:dot_index]
        extension = filename[dot_index:]
    else:
        stem = filename
        extension = ""
    return f"{stem} ({occurrence}){extension}"


def _receipt_identity_query(
    *,
    profile_key: str,
    folder_id: str,
    receipt_id: str,
    content_sha256: str | None,
) -> str:
    """Return the single Drive identity used for upload reconciliation."""
    clauses = [
            f"'{_escape_query_value(folder_id)}' in parents",
            "trashed = false",
            "appProperties has { key='tabulaRasaKind' and value='receipt' }",
            (
                "appProperties has { key='tabulaRasaProfile' and "
                f"value='{_escape_query_value(profile_key)}' }}"
            ),
            (
                "appProperties has { key='tabulaRasaReceiptId' and "
                f"value='{receipt_id}' }}"
            ),
        ]
    if content_sha256 is not None:
        clauses.append("appProperties has { key='tabulaRasaSha256' and " + f"value='{content_sha256}' }}")
    return " and ".join(clauses)


def _validate_recovery_identity(matches, filename, checksum):
    if matches and (len(matches) != 1 or matches[0].get('name') != filename
                    or matches[0].get('appProperties', {}).get('tabulaRasaSha256') != checksum):
        raise GoogleDriveConflictError('Inspect conflicting receipt identities or metadata before recovery.')



class _ReceiptOperationsMixin:
    """Receipt upload, inventory, backfill, and recovery operations."""

    def receipt_file(self, *, profile_key: str, folder_id: str, file_id: str) -> dict[str, Any]:
        """Resolve one current scoped receipt without scanning its entire folder."""
        folder_id = self._valid_folder_id(folder_id)
        file_id = self._valid_folder_id(file_id)
        response = self._request('GET', f'{DRIVE_API_ROOT}/files/{file_id}', params={
            'fields': 'id,name,mimeType,trashed,size,appProperties,parents',
            'supportsAllDrives': 'true',
        })
        file = dict(_json_response(response))
        properties = file.get('appProperties', {})
        if (file.get('id') != file_id or file.get('trashed')
                or folder_id not in file.get('parents', [])
                or not isinstance(properties, Mapping)
                or properties.get('tabulaRasaProfile') != profile_key
                or properties.get('tabulaRasaKind') != 'receipt'):
            raise GoogleDriveAccessError("The receipt is not in this profile's selected receipt folder.")
        return file

    def upload_receipt(
        self,
        *,
        profile_key: str,
        folder_id: str,
        original_name: str,
        content: bytes,
        mime_type: str,
        receipt_id: str | None = None,
        stored_filename: str | None = None,
    ) -> dict[str, Any]:
        """Create one receipt without replacing a same-named Drive file."""
        validate_receipt_upload(original_name, content)
        folder_id = self._valid_folder_id(folder_id)
        # Explicit recovery preserves both canonical names; ordinary uploads
        # retain basename normalization and automatic collision suffixes.
        try:
            base_filename = (validate_receipt_filename(stored_filename, 'Receipt stored filename')
                             if stored_filename is not None else safe_receipt_filename(original_name))
            original_filename = (validate_receipt_filename(original_name, 'Receipt original filename')
                                 if stored_filename is not None else safe_receipt_filename(original_name))
        except ReceiptManifestError:
            raise GoogleDriveAccessError('Receipt recovery filename metadata is invalid.') from None
        content_sha256 = hashlib.sha256(content).hexdigest()
        receipt_id = str(receipt_id or secrets.token_hex(16))
        if not RECEIPT_ID_PATTERN.fullmatch(receipt_id):
            raise GoogleDriveAccessError("Receipt identity is invalid.")
        identity_query = _receipt_identity_query(
            profile_key=profile_key,
            folder_id=folder_id,
            receipt_id=receipt_id,
            content_sha256=None if stored_filename is not None else content_sha256,
        )
        try:
            existing_by_identity = self._list(identity_query, page_size=2)
        except GoogleDriveAccessError as error:
            raise GoogleDriveAccessError(
                str(error),
                retryable=error.retryable,
                upload_attempted=False,
            ) from error
        if existing_by_identity:
            if stored_filename is not None:
                _validate_recovery_identity(existing_by_identity, stored_filename, content_sha256)
            uploaded = existing_by_identity[0]
            filename = str(uploaded.get("name") or base_filename)
        else:
            inventory_query = " and ".join(
                [
                    f"'{_escape_query_value(folder_id)}' in parents",
                    "trashed = false",
                ]
            )
            try:
                existing_names = {
                    str(item.get("name", "")).casefold()
                    for item in self._list(
                        inventory_query,
                        page_size=1000,
                        fetch_all=True,
                    )
                    if item.get("name")
                }
            except GoogleDriveAccessError as error:
                raise GoogleDriveAccessError(
                    str(error),
                    retryable=error.retryable,
                    upload_attempted=False,
                ) from error
            filename = ""
            if stored_filename is not None and base_filename.casefold() in existing_names:
                raise GoogleDriveConflictError('A different receipt already uses the recovery filename.')
            for occurrence in range(1, 1001):
                candidate = suffixed_receipt_filename(
                    base_filename,
                    occurrence,
                )
                if candidate.casefold() not in existing_names:
                    filename = candidate
                    break
            if not filename:
                raise GoogleDriveAccessError(
                    "Google Drive contains too many receipts with this filename. "
                    "Rename the local file and retry."
                )
        metadata = {
            "name": filename,
            "parents": [folder_id],
            "description": original_filename,
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": profile_key,
                "tabulaRasaReceiptId": receipt_id,
                "tabulaRasaSha256": content_sha256,
            },
        }
        if not existing_by_identity:
            try:
                uploaded = self._multipart_create(
                    metadata,
                    content,
                    mime_type or "application/octet-stream",
                )
            except GoogleDriveAccessError as error:
                if not error.retryable:
                    raise
                # One identity readback distinguishes a committed upload from
                # an unchanged Drive state. Only the latter gets one safe retry.
                try:
                    committed = self._list(identity_query, page_size=2)
                except GoogleDriveError as reconciliation_error:
                    raise error from reconciliation_error
                if committed:
                    if stored_filename is not None:
                        _validate_recovery_identity(committed, stored_filename, content_sha256)
                    uploaded = committed[0]
                else:
                    uploaded = self._multipart_create(
                        metadata,
                        content,
                        mime_type or "application/octet-stream",
                    )
        uploaded.setdefault("name", filename)
        uploaded.setdefault("mimeType", mime_type or "application/octet-stream")
        uploaded.setdefault("size", str(len(content)))
        uploaded.setdefault("description", original_filename)
        uploaded["appProperties"] = {
            **metadata["appProperties"],
            **(
                dict(uploaded.get("appProperties", {}))
                if isinstance(uploaded.get("appProperties"), Mapping)
                else {}
            ),
        }
        return uploaded


    def find_receipt_by_identity(
        self,
        *,
        profile_key: str,
        folder_id: str,
        receipt_id: str,
        content: bytes,
    ) -> dict[str, Any] | None:
        """Find an uncertain receipt without creating another Drive file."""
        folder_id = self._valid_folder_id(folder_id)
        if not RECEIPT_ID_PATTERN.fullmatch(str(receipt_id)):
            raise GoogleDriveAccessError("Receipt identity is invalid.")
        content_sha256 = hashlib.sha256(content).hexdigest()
        identity_query = _receipt_identity_query(
            profile_key=profile_key,
            folder_id=folder_id,
            receipt_id=receipt_id,
            content_sha256=content_sha256,
        )
        matches = self._list(identity_query, page_size=2)
        return dict(matches[0]) if matches else None


    def list_profile_receipts(
        self,
        *,
        profile_key: str,
        folder_id: str,
        _force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """List every app-managed receipt available to one profile."""
        folder_id = self._valid_folder_id(folder_id)
        query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                (
                    "appProperties has { key='tabulaRasaKind' and "
                    "value='receipt' }"
                ),
                (
                    "appProperties has { key='tabulaRasaProfile' and "
                    f"value='{_escape_query_value(profile_key)}' }}"
                ),
            ]
        )
        return self._list(
            query,
            page_size=1000,
            order_by="createdTime desc",
            use_cache=not _force_refresh,
            fetch_all=True,
        )


    def backfill_receipt_checksum(
        self,
        *,
        profile_key: str,
        folder_id: str,
        file_id: str,
    ) -> dict[str, Any]:
        """Download one legacy receipt once and persist verified integrity metadata."""
        receipts = self.list_profile_receipts(
            profile_key=profile_key,
            folder_id=folder_id,
            _force_refresh=True,
        )
        matches = [item for item in receipts if str(item.get("id")) == str(file_id)]
        if len(matches) != 1:
            raise GoogleDriveAccessError(
                "The legacy receipt is not in this profile's selected receipt folder."
            )
        receipt = matches[0]
        try:
            receipt_reference_from_drive_file(receipt)
        except ReceiptManifestError:
            pass
        else:
            return receipt

        content = self.download_file(str(file_id))
        if not content or len(content) > MAX_RECEIPT_BYTES:
            raise GoogleDriveAccessError(
                "The legacy receipt is empty or exceeds the supported receipt size."
            )
        properties = receipt.get("appProperties")
        existing_properties = (
            dict(properties) if isinstance(properties, Mapping) else {}
        )
        existing_receipt_id = _clean_text(
            existing_properties.get("tabulaRasaReceiptId"), maximum=32
        )
        deterministic_legacy_id = hashlib.sha256(
            (
                "tabula-rasa-legacy-receipt:"
                f"{profile_key}:{file_id}"
            ).encode("utf-8")
        ).hexdigest()[:32]
        receipt_id = (
            existing_receipt_id
            if RECEIPT_ID_PATTERN.fullmatch(existing_receipt_id)
            else deterministic_legacy_id
        )
        patch_properties = {
            **existing_properties,
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": profile_key,
            "tabulaRasaReceiptId": receipt_id,
            "tabulaRasaSha256": hashlib.sha256(content).hexdigest(),
        }
        original_filename = safe_receipt_filename(
            str(
                receipt.get("description")
                or existing_properties.get("tabulaRasaOriginalName")
                or receipt.get("name")
                or "receipt"
            )
        )
        self._invalidate_list_cache()
        response = self._request(
            "PATCH",
            f"{DRIVE_API_ROOT}/files/{file_id}",
            params={
                "fields": (
                    "id,name,mimeType,size,createdTime,modifiedTime,"
                    "description,webViewLink,appProperties,parents"
                ),
                "supportsAllDrives": "true",
            },
            headers={"Content-Type": "application/json; charset=UTF-8"},
            data=json.dumps(
                {
                    "appProperties": patch_properties,
                    "description": original_filename,
                }
            ),
        )
        updated = dict(_json_response(response))
        updated.setdefault("id", str(file_id))
        updated.setdefault("name", str(receipt.get("name") or "receipt"))
        updated.setdefault(
            "mimeType", str(receipt.get("mimeType") or "application/octet-stream")
        )
        updated.setdefault("size", str(len(content)))
        updated.setdefault("description", original_filename)
        updated["appProperties"] = patch_properties
        try:
            receipt_reference_from_drive_file(updated)
        except ReceiptManifestError as exc:
            raise GoogleDriveAccessError(
                "Google Drive did not confirm the receipt integrity backfill."
            ) from exc
        return updated


    def restore_receipt(
        self,
        *,
        profile_key: str,
        folder_id: str,
        stored_filename: str,
        original_filename: str,
        content: bytes,
        mime_type: str,
        receipt_id: str,
        sha256: str,
        old_file_id: str,
    ) -> tuple[dict[str, Any], bool]:
        """Create or reuse one verified recovery file without suffixing its name."""
        try:
            stored_filename = validate_receipt_filename(
                stored_filename,
                "Receipt stored filename",
            )
            original_filename = validate_receipt_filename(
                original_filename,
                "Receipt original filename",
            )
        except ReceiptManifestError as exc:
            raise GoogleDriveAccessError(
                "Receipt recovery metadata or content failed integrity validation."
            ) from exc
        if (
            not content
            or len(content) > MAX_RECEIPT_BYTES
            or hashlib.sha256(content).hexdigest() != sha256
            or not RECEIPT_ID_PATTERN.fullmatch(str(receipt_id))
            or not SHA256_PATTERN.fullmatch(str(sha256))
            or not RECEIPT_DRIVE_ID_PATTERN.fullmatch(str(old_file_id))
        ):
            raise GoogleDriveAccessError(
                "Receipt recovery metadata or content failed integrity validation."
            )
        folder_id = self._valid_folder_id(folder_id)
        identity_query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                (
                    "appProperties has { key='tabulaRasaKind' and "
                    "value='receipt' }"
                ),
                (
                    "appProperties has { key='tabulaRasaProfile' and "
                    f"value='{_escape_query_value(profile_key)}' }}"
                ),
                (
                    "appProperties has { key='tabulaRasaReceiptId' and "
                    f"value='{receipt_id}' }}"
                ),
                (
                    "appProperties has { key='tabulaRasaSha256' and "
                    f"value='{sha256}' }}"
                ),
            ]
        )
        existing_identity = self._list(identity_query, page_size=2)
        if len(existing_identity) > 1:
            raise GoogleDriveConflictError(
                "Google Drive contains duplicate files for this receipt identity."
            )
        if existing_identity:
            existing = existing_identity[0]
            try:
                reference = receipt_reference_from_drive_file(existing)
            except ReceiptManifestError as exc:
                raise GoogleDriveConflictError(
                    "An existing recovered receipt has inconsistent metadata."
                ) from exc
            if (
                reference["name"] != stored_filename
                or reference["original_filename"] != original_filename
                or reference["mime_type"] != mime_type
                or reference["byte_size"] != len(content)
            ):
                raise GoogleDriveConflictError(
                    "An existing recovered receipt conflicts with the manifest."
                )
            existing_content = self.download_file(str(reference["id"]))
            if (
                len(existing_content) != len(content)
                or hashlib.sha256(existing_content).hexdigest() != sha256
            ):
                raise GoogleDriveConflictError(
                    "An existing recovered receipt failed checksum verification."
                )
            return existing, True

        filename_inventory_query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
            ]
        )
        existing_names = {
            str(item.get("name", "")).casefold()
            for item in self._list(
                filename_inventory_query,
                page_size=1000,
                fetch_all=True,
            )
            if item.get("name")
        }
        if stored_filename.casefold() in existing_names:
            raise GoogleDriveConflictError(
                "A different Google Drive file already uses the recovery filename."
            )
        properties = {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": profile_key,
            "tabulaRasaReceiptId": receipt_id,
            "tabulaRasaSha256": sha256,
            "tabulaRasaOriginalFileId": old_file_id,
        }
        recovery_attempt_id = secrets.token_hex(16)
        metadata = {
            "name": stored_filename,
            "parents": [folder_id],
            "description": original_filename,
            "appProperties": {
                **properties,
                "tabulaRasaRecoveryAttempt": recovery_attempt_id,
            },
        }
        recovered_after_uncertain_response = False
        created_file_id = ""
        redundant_created_file_id = ""
        try:
            uploaded = self._multipart_create(metadata, content, mime_type)
            created_file_id = str(uploaded.get("id", ""))
        except GoogleDriveAccessError as error:
            if not error.retryable:
                raise
            recovered_after_uncertain_response = True
        committed = self._list(identity_query, page_size=1000)
        if not committed:
            raise GoogleDriveAccessError(
                "Google Drive did not confirm the recovered receipt upload."
            )
        attempt_matches = [
            item
            for item in committed
            if isinstance(item.get("appProperties"), Mapping)
            and item["appProperties"].get("tabulaRasaRecoveryAttempt")
            == recovery_attempt_id
        ]
        if len(attempt_matches) > 1:
            raise GoogleDriveConflictError(
                "Google Drive contains duplicate files for this recovery attempt."
            )
        if not created_file_id and attempt_matches:
            created_file_id = str(attempt_matches[0].get("id", ""))
        uploaded = min(
            committed,
            key=lambda item: (
                str(item.get("createdTime", "")),
                str(item.get("id", "")),
            ),
        )
        if created_file_id and str(uploaded.get("id", "")) != created_file_id:
            redundant_created_file_id = created_file_id
            recovered_after_uncertain_response = True
        uploaded.setdefault("name", stored_filename)
        uploaded.setdefault("mimeType", mime_type)
        uploaded.setdefault("size", str(len(content)))
        uploaded.setdefault("description", original_filename)
        uploaded["appProperties"] = {
            **properties,
            **(
                dict(uploaded.get("appProperties", {}))
                if isinstance(uploaded.get("appProperties"), Mapping)
                else {}
            ),
        }
        try:
            reference = receipt_reference_from_drive_file(uploaded)
        except ReceiptManifestError as exc:
            raise GoogleDriveAccessError(
                "Google Drive did not confirm the recovered receipt metadata."
            ) from exc
        if (
            reference["name"] != stored_filename
            or reference["original_filename"] != original_filename
            or reference["mime_type"] != mime_type
            or reference["byte_size"] != len(content)
        ):
            raise GoogleDriveConflictError(
                "A concurrent recovered receipt conflicts with the manifest."
            )
        if recovered_after_uncertain_response:
            committed_content = self.download_file(str(uploaded["id"]))
            if (
                len(committed_content) != len(content)
                or hashlib.sha256(committed_content).hexdigest() != sha256
            ):
                raise GoogleDriveConflictError(
                    "The recovered Google Drive upload failed checksum verification."
                )
        if redundant_created_file_id:
            # A concurrent recovery created the same stable identity first.
            # Only discard this invocation's later file after the canonical
            # object is fully validated, so callers converge without orphaning
            # a reference returned by another recovery command.
            self.delete_file(redundant_created_file_id)
        return uploaded, False
