from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import pytest
import requests

from tabula_rasa.google_drive import (
    GoogleDriveAccessError, GoogleDriveClient, GoogleDriveConflictError,
)

from ._support import FakeResponse, DriveSession, drive_settings, oauth_config

class TestGoogleDriveReceiptRecovery:
    def test_receipt_recovery_propagates_nonretryable_upload_failure(self) -> None:
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                FakeResponse(400, {"error": {"message": "invalid request"}}),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with pytest.raises(GoogleDriveAccessError) as raised:
            client.restore_receipt(
                profile_key="north",
                folder_id="folder123456",
                stored_filename="statement.pdf",
                original_filename="statement.pdf",
                content=b"receipt",
                mime_type="application/pdf",
                receipt_id="a" * 32,
                sha256=hashlib.sha256(b"receipt").hexdigest(),
                old_file_id="receipt123456",
            )

        assert raised.value.retryable is False
        assert [request[0] for request in session.requests] == [
            "GET",
            "GET",
            "POST",
        ]

    def test_receipt_recovery_preserves_name_and_integrity_metadata(self) -> None:
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                FakeResponse(
                    200,
                    {"id": "restored123456", "name": "statement (2).pdf"},
                ),
                FakeResponse(
                    200,
                    {
                        "files": [
                            {
                                "id": "restored123456",
                                "name": "statement (2).pdf",
                            }
                        ]
                    },
                ),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )
        checksum = hashlib.sha256(b"receipt").hexdigest()

        restored, reused = client.restore_receipt(
            profile_key="north",
            folder_id="folder123456",
            stored_filename="statement (2).pdf",
            original_filename="statement.pdf",
            content=b"receipt",
            mime_type="application/pdf",
            receipt_id="a" * 32,
            sha256=checksum,
            old_file_id="receipt123456",
        )

        assert reused is False
        assert restored["name"] == "statement (2).pdf"
        assert restored["appProperties"] == {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": "north",
            "tabulaRasaReceiptId": "a" * 32,
            "tabulaRasaSha256": checksum,
            "tabulaRasaOriginalFileId": "receipt123456",
        }
        assert restored["description"] == "statement.pdf"
        assert [request[0] for request in session.requests] == [
            "GET",
            "GET",
            "POST",
            "GET",
        ]
        upload_body = next(
            request[2]["data"]
            for request in session.requests
            if request[0] == "POST"
        )
        assert b'"name":"statement (2).pdf"' in upload_body


    def test_receipt_recovery_preserves_manifest_safe_unicode_names(self) -> None:
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"id": "restored123456", "name": "résumé.pdf"}),
                FakeResponse(
                    200,
                    {"files": [{"id": "restored123456", "name": "résumé.pdf"}]},
                ),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )
        checksum = hashlib.sha256(b"receipt").hexdigest()

        restored, reused = client.restore_receipt(
            profile_key="north",
            folder_id="folder123456",
            stored_filename="résumé.pdf",
            original_filename="résumé original.pdf",
            content=b"receipt",
            mime_type="application/pdf",
            receipt_id="a" * 32,
            sha256=checksum,
            old_file_id="receipt123456",
        )

        assert reused is False
        assert restored["name"] == "résumé.pdf"
        assert restored["description"] == "résumé original.pdf"
        upload_body = next(
            request[2]["data"]
            for request in session.requests
            if request[0] == "POST"
        )
        assert json.dumps("résumé.pdf").encode() in upload_body


    def test_receipt_recovery_reuses_stable_identity_and_checksum(self) -> None:
        checksum = hashlib.sha256(b"receipt").hexdigest()
        existing = {
            "id": "restored123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": "north",
                "tabulaRasaReceiptId": "a" * 32,
                "tabulaRasaSha256": checksum,
                "tabulaRasaOriginalName": "statement.pdf",
                "tabulaRasaOriginalFileId": "receipt123456",
            },
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": [existing]}),
                FakeResponse(200, content=b"receipt"),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        restored, reused = client.restore_receipt(
            profile_key="north",
            folder_id="folder123456",
            stored_filename="statement.pdf",
            original_filename="statement.pdf",
            content=b"receipt",
            mime_type="application/pdf",
            receipt_id="a" * 32,
            sha256=checksum,
            old_file_id="receipt123456",
        )

        assert restored == existing
        assert reused is True
        assert [request[0] for request in session.requests] == ["GET", "GET"]


    def test_receipt_recovery_refuses_a_case_only_filename_collision(
        self,
    ) -> None:
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(
                    200,
                    {"files": [{"id": "different123456", "name": "Statement.pdf"}]},
                ),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with pytest.raises(GoogleDriveConflictError, match="recovery filename"):
            client.restore_receipt(
                profile_key="north",
                folder_id="folder123456",
                stored_filename="statement.pdf",
                original_filename="statement.pdf",
                content=b"receipt",
                mime_type="application/pdf",
                receipt_id="a" * 32,
                sha256=hashlib.sha256(b"receipt").hexdigest(),
                old_file_id="receipt123456",
            )

        assert [request[0] for request in session.requests] == ["GET", "GET"]
        assert "name =" not in session.requests[-1][2]["params"]["q"]
        assert session.requests[-1][2]["params"]["pageSize"] == 1000


    def test_receipt_recovery_refuses_corrupt_existing_identity(self) -> None:
        checksum = hashlib.sha256(b"receipt").hexdigest()
        existing = {
            "id": "restored123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "description": "statement.pdf",
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": "north",
                "tabulaRasaReceiptId": "a" * 32,
                "tabulaRasaSha256": checksum,
            },
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": [existing]}),
                FakeResponse(200, content=b"corrupt"),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with pytest.raises(GoogleDriveConflictError, match="checksum"):
            client.restore_receipt(
                profile_key="north",
                folder_id="folder123456",
                stored_filename="statement.pdf",
                original_filename="statement.pdf",
                content=b"receipt",
                mime_type="application/pdf",
                receipt_id="a" * 32,
                sha256=checksum,
                old_file_id="receipt123456",
            )

        assert [request[0] for request in session.requests] == ["GET", "GET"]


    def test_receipt_recovery_recovers_an_uncertain_create_without_duplication(
        self,
    ) -> None:
        checksum = hashlib.sha256(b"receipt").hexdigest()
        committed = {
            "id": "restored123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": "north",
                "tabulaRasaReceiptId": "a" * 32,
                "tabulaRasaSha256": checksum,
                "tabulaRasaOriginalName": "statement.pdf",
            },
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                requests.ConnectionError("response lost"),
                FakeResponse(200, {"files": [committed]}),
                FakeResponse(200, content=b"receipt"),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        restored, reused = client.restore_receipt(
            profile_key="north",
            folder_id="folder123456",
            stored_filename="statement.pdf",
            original_filename="statement.pdf",
            content=b"receipt",
            mime_type="application/pdf",
            receipt_id="a" * 32,
            sha256=checksum,
            old_file_id="receipt123456",
        )

        assert restored["id"] == "restored123456"
        assert reused is False
        assert [request[0] for request in session.requests].count("POST") == 1


    def test_receipt_recovery_reconciles_a_lost_concurrent_create_response(
        self,
    ) -> None:
        checksum = hashlib.sha256(b"receipt").hexdigest()
        properties = {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": "north",
            "tabulaRasaReceiptId": "a" * 32,
            "tabulaRasaSha256": checksum,
            "tabulaRasaOriginalFileId": "receipt123456",
        }
        canonical = {
            "id": "restored123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "createdTime": "2026-08-01T12:00:00Z",
            "description": "statement.pdf",
            "appProperties": {
                **properties,
                "tabulaRasaRecoveryAttempt": "other-attempt",
            },
        }
        uncertain = {
            **canonical,
            "id": "restored234567",
            "createdTime": "2026-08-01T12:00:01Z",
            "appProperties": {
                **properties,
                "tabulaRasaRecoveryAttempt": "1" * 32,
            },
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                requests.ConnectionError("response lost"),
                FakeResponse(200, {"files": [uncertain, canonical]}),
                FakeResponse(200, content=b"receipt"),
                FakeResponse(204),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with patch(
            "tabula_rasa.google_drive.receipts.secrets.token_hex",
            side_effect=["1" * 32, "2" * 32],
        ):
            restored, reused = client.restore_receipt(
                profile_key="north",
                folder_id="folder123456",
                stored_filename="statement.pdf",
                original_filename="statement.pdf",
                content=b"receipt",
                mime_type="application/pdf",
                receipt_id="a" * 32,
                sha256=checksum,
                old_file_id="receipt123456",
            )

        assert restored["id"] == canonical["id"]
        assert reused is False
        assert [request[0] for request in session.requests] == [
            "GET",
            "GET",
            "POST",
            "GET",
            "GET",
            "DELETE",
        ]
        assert b'"tabulaRasaRecoveryAttempt":"11111111111111111111111111111111"' in (
            session.requests[2][2]["data"]
        )
        assert session.requests[5][1].endswith("/files/restored234567")


    def test_receipt_recovery_discards_its_concurrent_later_create(
        self,
    ) -> None:
        checksum = hashlib.sha256(b"receipt").hexdigest()
        properties = {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": "north",
            "tabulaRasaReceiptId": "a" * 32,
            "tabulaRasaSha256": checksum,
            "tabulaRasaOriginalFileId": "receipt123456",
        }
        canonical = {
            "id": "restored123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "createdTime": "2026-08-01T12:00:00Z",
            "description": "statement.pdf",
            "appProperties": properties,
        }
        later = {
            **canonical,
            "id": "restored234567",
            "createdTime": "2026-08-01T12:00:01Z",
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                FakeResponse(200, later),
                FakeResponse(200, {"files": [later, canonical]}),
                FakeResponse(200, content=b"receipt"),
                FakeResponse(204),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        restored, reused = client.restore_receipt(
            profile_key="north",
            folder_id="folder123456",
            stored_filename="statement.pdf",
            original_filename="statement.pdf",
            content=b"receipt",
            mime_type="application/pdf",
            receipt_id="a" * 32,
            sha256=checksum,
            old_file_id="receipt123456",
        )

        assert restored["id"] == canonical["id"]
        assert reused is False
        assert [request[0] for request in session.requests] == [
            "GET",
            "GET",
            "POST",
            "GET",
            "GET",
            "DELETE",
        ]
        assert session.requests[5][1].endswith("/files/restored234567")
